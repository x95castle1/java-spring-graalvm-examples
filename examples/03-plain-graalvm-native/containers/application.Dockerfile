# syntax=docker/dockerfile:1
ARG JAVA_IMAGE=eclipse-temurin:25-jdk-noble@sha256:589ff4cc3f71aab462e7048a47a0d10edf57fbccde3fceea2281e610bf5880b4
ARG NATIVE_IMAGE=ghcr.io/graalvm/native-image-community:25-ol9@sha256:7d17320ffc98d5aaffdf8c1aae929e659dc440f7a7722eb5ad2cade1ac834af7
ARG RUNTIME_IMAGE=oraclelinux:9-slim@sha256:fdf4581abc841d49f63cf456ea92f8152a80b5bdc62d5409a4e77827b824265c
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

FROM ${NATIVE_IMAGE} AS native-build
ARG NATIVE_IMAGE
ARG RUNTIME_IMAGE
WORKDIR /app
RUN microdnf install -y time && microdnf clean all
COPY --from=build /workspace/build/libs/plain-java.jar /app/plain-java.jar
RUN native-image --version > /app/native-version.txt \
    && printf '%s\n' "${NATIVE_IMAGE}" > /app/native-image.txt \
    && printf '%s\n' "${RUNTIME_IMAGE}" > /app/runtime-image.txt
RUN if /usr/bin/time -o /app/native-build.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      native-image --no-fallback --gc=serial -march=compatibility \
      --exact-reachability-metadata --parallelism=2 -J-Xmx2g \
      -jar /app/plain-java.jar /app/catalog-cli > /app/native-build.log 2>&1; \
    then cat /app/native-build.log; else cat /app/native-build.log; exit 1; fi

FROM ${RUNTIME_IMAGE} AS application
WORKDIR /app
RUN microdnf install -y zlib && microdnf clean all
COPY --from=native-build /app/catalog-cli /app/catalog-cli
USER 10001
ENTRYPOINT ["/app/catalog-cli", "-Xmx256m"]

FROM ${JAVA_IMAGE} AS benchmark
ARG JAVA_IMAGE
WORKDIR /app
COPY --from=build /workspace/build/libs/plain-java.jar /app/plain-java.jar
COPY --from=build /workspace/source.sha256 /app/source.sha256
COPY --from=native-build /app/catalog-cli /app/catalog-cli
COPY --from=native-build /app/native-build.json /app/native-build.log /app/
COPY --from=native-build /app/native-version.txt /app/native-image.txt /app/runtime-image.txt /app/
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/run.py"]
