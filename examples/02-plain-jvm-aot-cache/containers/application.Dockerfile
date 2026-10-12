# syntax=docker/dockerfile:1
ARG JAVA_IMAGE=eclipse-temurin:25-jdk-noble@sha256:589ff4cc3f71aab462e7048a47a0d10edf57fbccde3fceea2281e610bf5880b4
FROM ${JAVA_IMAGE} AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle gradle.properties ./
COPY src/ src/
RUN find build.gradle settings.gradle gradle.properties gradlew gradle src -type f -print0 \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1 > /workspace/source.sha256
RUN --mount=type=cache,target=/root/.gradle ./gradlew --no-daemon --console=plain build

FROM ${JAVA_IMAGE} AS packaged
ARG JAVA_IMAGE
WORKDIR /app
COPY --from=build /workspace/build/libs/plain-java.jar /app/plain-java.jar
COPY --from=build /workspace/source.sha256 /app/source.sha256
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt
ENTRYPOINT ["java", "-Xmx256m", "-XX:+UseG1GC", "-jar", "/app/plain-java.jar"]

FROM packaged AS training
ARG TRAIN_ITERATIONS=100000
RUN apt-get update \
    && apt-get install -y --no-install-recommends time \
    && rm -rf /var/lib/apt/lists/*
RUN /usr/bin/time -o /app/short-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      java -Xmx256m -XX:+UseG1GC \
      -XX:AOTCacheOutput=/app/short.aot \
      -Xlog:aot=info:file=/app/short-training.log \
      -jar /app/plain-java.jar --iterations 1 \
    && test -s /app/short.aot
RUN /usr/bin/time -o /app/workload-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      java -Xmx256m -XX:+UseG1GC \
      -XX:AOTCacheOutput=/app/workload.aot \
      -Xlog:aot=info:file=/app/workload-training.log \
      -jar /app/plain-java.jar --iterations ${TRAIN_ITERATIONS} \
    && test -s /app/workload.aot \
    && printf '%s\n' ${TRAIN_ITERATIONS} > /app/training-iterations.txt

FROM packaged AS application
COPY --from=training /app/short.aot /app/workload.aot /app/
COPY --from=training /app/short-training.json /app/workload-training.json /app/
COPY --from=training /app/short-training.log /app/workload-training.log /app/
COPY --from=training /app/training-iterations.txt /app/
ENTRYPOINT ["java", "-Xmx256m", "-XX:+UseG1GC", "-XX:AOTMode=on", "-XX:AOTCache=/app/workload.aot", "-jar", "/app/plain-java.jar"]

FROM application AS benchmark
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/run.py"]
