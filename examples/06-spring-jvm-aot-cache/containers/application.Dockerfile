# syntax=docker/dockerfile:1
ARG JAVA_IMAGE=eclipse-temurin:25-jdk-noble@sha256:589ff4cc3f71aab462e7048a47a0d10edf57fbccde3fceea2281e610bf5880b4
FROM ${JAVA_IMAGE} AS build
RUN apt-get update && apt-get install -y --no-install-recommends unzip time \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle gradle.properties ./
COPY src/ src/
RUN find build.gradle settings.gradle gradle.properties gradlew gradle src -type f -print0 | sort -z | xargs -0 sha256sum \
    | sha256sum | cut -d ' ' -f 1 > /workspace/source.sha256
RUN --mount=type=cache,target=/root/.gradle \
    if /usr/bin/time -o /workspace/packaging.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain build > /workspace/packaging.log 2>&1; \
    then cat /workspace/packaging.log; else cat /workspace/packaging.log; exit 1; fi
RUN java -Djarmode=tools -jar build/libs/catalog-service.jar extract --destination /workspace/application

FROM ${JAVA_IMAGE} AS packaged
ARG JAVA_IMAGE
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /workspace/application/ /app/
COPY --from=build /workspace/source.sha256 /workspace/packaging.json /workspace/packaging.log /app/
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt \
    && printf '%s\n' '4.1.1' > /app/boot-version.txt

FROM packaged AS training
ARG TRAIN_REQUESTS=200
ARG TRAIN_ITERATIONS=100000
RUN apt-get update && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
COPY containers/train.py /training/train.py
RUN /usr/bin/time -o /app/short-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      java -Xmx256m -XX:+UseG1GC -Dspring.aot.enabled=false \
      -XX:AOTCacheOutput=/app/short.aot -Dspring.context.exit=onRefresh \
      -Xlog:aot=info:file=/app/short-training.log -jar /app/catalog-service.jar \
    && test -s /app/short.aot
RUN /usr/bin/time -o /app/workload-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      python3 /training/train.py ${TRAIN_REQUESTS} ${TRAIN_ITERATIONS} \
    && test -s /app/workload.aot \
    && printf '%s\n' ${TRAIN_REQUESTS} > /app/training-requests.txt \
    && printf '%s\n' ${TRAIN_ITERATIONS} > /app/training-iterations.txt

FROM packaged AS application
COPY --from=training /app/short.aot /app/workload.aot /app/
COPY --from=training /app/short-training.json /app/workload-training.json /app/
COPY --from=training /app/short-training.log /app/workload-training.log /app/
COPY --from=training /app/training-requests.txt /app/training-iterations.txt /app/

ENTRYPOINT ["java", "-Xmx256m", "-XX:+UseG1GC", "-Dspring.aot.enabled=false", "-XX:AOTMode=on", "-XX:AOTCache=/app/workload.aot", "-jar", "/app/catalog-service.jar"]

FROM application AS benchmark
RUN apt-get update && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/http_run.py"]
