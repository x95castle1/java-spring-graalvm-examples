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

FROM ${JAVA_IMAGE} AS application
ARG JAVA_IMAGE
WORKDIR /app
COPY --from=build /workspace/build/libs/plain-java.jar /app/plain-java.jar
COPY --from=build /workspace/source.sha256 /app/source.sha256
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt
ENTRYPOINT ["java", "-Xmx256m", "-XX:+UseG1GC", "-jar", "/app/plain-java.jar"]

FROM application AS benchmark
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/run.py"]
