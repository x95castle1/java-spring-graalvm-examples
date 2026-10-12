# syntax=docker/dockerfile:1
ARG JAVA_IMAGE=eclipse-temurin:25-jdk-noble@sha256:589ff4cc3f71aab462e7048a47a0d10edf57fbccde3fceea2281e610bf5880b4
ARG NATIVE_IMAGE=ghcr.io/graalvm/native-image-community:25-ol9@sha256:7d17320ffc98d5aaffdf8c1aae929e659dc440f7a7722eb5ad2cade1ac834af7
ARG RUNTIME_IMAGE=oraclelinux:9-slim@sha256:fdf4581abc841d49f63cf456ea92f8152a80b5bdc62d5409a4e77827b824265c
FROM ${NATIVE_IMAGE} AS native-build
ARG NATIVE_IMAGE
ARG RUNTIME_IMAGE
WORKDIR /workspace
RUN microdnf install -y time unzip findutils && microdnf clean all
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle gradle.properties ./
COPY src/ src/
RUN find build.gradle settings.gradle gradle.properties gradlew gradle src -type f -print0 \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1 > /workspace/source.sha256
RUN --mount=type=cache,target=/root/.gradle \
    if /usr/bin/time -o /workspace/packaging.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain build > /workspace/packaging.log 2>&1; \
    then cat /workspace/packaging.log; else cat /workspace/packaging.log; exit 1; fi
RUN --mount=type=cache,target=/root/.gradle \
    if /usr/bin/time -o /workspace/native-build.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain nativeCompile > /workspace/native-build.log 2>&1; \
    then cat /workspace/native-build.log; else cat /workspace/native-build.log; exit 1; fi
RUN java -Djarmode=tools -jar build/libs/catalog-service.jar extract --destination /workspace/application \
    && native-image --version > /workspace/native-version.txt \
    && printf '%s\n' "${NATIVE_IMAGE}" > /workspace/native-image.txt \
    && printf '%s\n' "${RUNTIME_IMAGE}" > /workspace/runtime-image.txt
FROM ${RUNTIME_IMAGE} AS application
WORKDIR /app
RUN microdnf install -y zlib curl && microdnf clean all
COPY --from=native-build /workspace/build/native/nativeCompile/catalog-service /app/catalog-service
USER 10001
ENTRYPOINT ["/app/catalog-service", "-Xmx256m"]
FROM ${JAVA_IMAGE} AS benchmark
ARG JAVA_IMAGE
WORKDIR /app
COPY --from=native-build /workspace/application/ /app/
COPY --from=native-build /workspace/build/native/nativeCompile/catalog-service /app/catalog-service
COPY --from=native-build /workspace/source.sha256 /workspace/packaging.json /workspace/packaging.log /app/
COPY --from=native-build /workspace/native-build.json /workspace/native-build.log /app/
COPY --from=native-build /workspace/native-version.txt /workspace/native-image.txt /workspace/runtime-image.txt /app/
COPY --from=native-build /workspace/build/generated/ /app/spring-aot/
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt \
    && printf '%s\n' '4.1.1' > /app/boot-version.txt
RUN apt-get update && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/http_run.py"]
