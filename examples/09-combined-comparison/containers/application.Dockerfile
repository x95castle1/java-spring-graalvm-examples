# syntax=docker/dockerfile:1
ARG JAVA_IMAGE=eclipse-temurin:25-jdk-noble@sha256:589ff4cc3f71aab462e7048a47a0d10edf57fbccde3fceea2281e610bf5880b4
ARG NATIVE_IMAGE=ghcr.io/graalvm/native-image-community:25-ol9@sha256:7d17320ffc98d5aaffdf8c1aae929e659dc440f7a7722eb5ad2cade1ac834af7
ARG RUNTIME_IMAGE=oraclelinux:9-slim@sha256:fdf4581abc841d49f63cf456ea92f8152a80b5bdc62d5409a4e77827b824265c
FROM ${NATIVE_IMAGE} AS plain-build
RUN microdnf install -y time unzip findutils && microdnf clean all
WORKDIR /workspace
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle gradle.properties ./
COPY src/ src/
RUN find build.gradle settings.gradle gradle.properties gradlew gradle src -type f -print0 | sort -z | xargs -0 sha256sum \
    | sha256sum | cut -d ' ' -f 1 > /workspace/source.sha256
RUN --mount=type=cache,id=aot-example-09-gradle,target=/root/.gradle,sharing=locked \
    if /usr/bin/time -o /workspace/plain-packaging.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain -Pplain=true build > /workspace/plain-packaging.log 2>&1; \
    then cat /workspace/plain-packaging.log; else cat /workspace/plain-packaging.log; exit 1; fi
RUN java -Djarmode=tools -jar build/plain/libs/catalog-service.jar extract --destination /workspace/plain-application

FROM ${NATIVE_IMAGE} AS aot-build
ARG NATIVE_IMAGE
ARG RUNTIME_IMAGE
WORKDIR /workspace
RUN microdnf install -y time unzip findutils && microdnf clean all
COPY gradle/ gradle/
COPY gradlew build.gradle settings.gradle gradle.properties ./
COPY src/ src/
RUN find build.gradle settings.gradle gradle.properties gradlew gradle src -type f -print0 \
    | sort -z | xargs -0 sha256sum | sha256sum | cut -d ' ' -f 1 > /workspace/source.sha256
RUN --mount=type=cache,id=aot-example-09-gradle,target=/root/.gradle,sharing=locked \
    if /usr/bin/time -o /workspace/aot-packaging.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain build > /workspace/aot-packaging.log 2>&1; \
    then cat /workspace/aot-packaging.log; else cat /workspace/aot-packaging.log; exit 1; fi
RUN java -Djarmode=tools -jar build/aot/libs/catalog-service.jar extract --destination /workspace/aot-application \
    && native-image --version > /workspace/native-version.txt \
    && printf '%s\n' "${NATIVE_IMAGE}" > /workspace/native-image.txt \
    && printf '%s\n' "${RUNTIME_IMAGE}" > /workspace/runtime-image.txt
FROM aot-build AS native-build
RUN --mount=type=cache,id=aot-example-09-gradle,target=/root/.gradle,sharing=locked \
    if /usr/bin/time -o /workspace/native-build.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      ./gradlew --no-daemon --console=plain nativeCompile > /workspace/native-build.log 2>&1; \
    then cat /workspace/native-build.log; else cat /workspace/native-build.log; exit 1; fi
FROM ${JAVA_IMAGE} AS packaged
ARG JAVA_IMAGE
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=plain-build /workspace/plain-application/ /app/plain/
COPY --from=aot-build /workspace/aot-application/ /app/aot/
COPY --from=aot-build /workspace/source.sha256 /app/source.sha256
COPY --from=plain-build /workspace/plain-packaging.json /workspace/plain-packaging.log /app/
COPY --from=aot-build /workspace/aot-packaging.json /workspace/aot-packaging.log /app/
COPY --from=aot-build /workspace/build/aot/generated/ /app/spring-aot/
RUN printf '%s\n' "${JAVA_IMAGE}" > /app/java-image.txt \
    && printf '%s\n' '4.1.1' > /app/boot-version.txt

FROM packaged AS training
ARG TRAIN_REQUESTS=200
ARG TRAIN_ITERATIONS=100000
RUN apt-get update && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
COPY containers/train.py /training/train.py
RUN TRAIN_JAR=/app/plain/catalog-service.jar TRAIN_SPRING_AOT=false CACHE_NAME=jvm-cache \
    /usr/bin/time -o /app/jvm-cache-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      python3 /training/train.py ${TRAIN_REQUESTS} ${TRAIN_ITERATIONS} \
    && test -s /app/jvm-cache.aot
RUN TRAIN_JAR=/app/aot/catalog-service.jar TRAIN_SPRING_AOT=true CACHE_NAME=spring-aot-cache \
    /usr/bin/time -o /app/spring-aot-cache-training.json \
      -f '{"elapsed_seconds":%e,"user_cpu_seconds":%U,"system_cpu_seconds":%S,"peak_rss_kib":%M}' \
      python3 /training/train.py ${TRAIN_REQUESTS} ${TRAIN_ITERATIONS} \
    && test -s /app/spring-aot-cache.aot \
    && printf '%s\n' ${TRAIN_REQUESTS} > /app/training-requests.txt \
    && printf '%s\n' ${TRAIN_ITERATIONS} > /app/training-iterations.txt

FROM packaged AS application
COPY --from=training /app/jvm-cache.aot /app/spring-aot-cache.aot /app/
COPY --from=training /app/jvm-cache-training.json /app/spring-aot-cache-training.json /app/
COPY --from=training /app/jvm-cache-training.log /app/spring-aot-cache-training.log /app/
COPY --from=training /app/training-requests.txt /app/training-iterations.txt /app/
ENTRYPOINT ["java", "-Xmx256m", "-XX:+UseG1GC", "-Dspring.aot.enabled=true", "-XX:AOTMode=on", "-XX:AOTCache=/app/spring-aot-cache.aot", "-jar", "/app/aot/catalog-service.jar"]

FROM ${RUNTIME_IMAGE} AS native-application
WORKDIR /app
RUN microdnf install -y zlib curl && microdnf clean all
COPY --from=native-build /workspace/build/aot/native/nativeCompile/catalog-service /app/catalog-service
USER 10001
ENTRYPOINT ["/app/catalog-service", "-Xmx256m"]

FROM application AS benchmark
COPY --from=native-build /workspace/build/aot/native/nativeCompile/catalog-service /app/catalog-service
COPY --from=native-build /workspace/native-build.json /workspace/native-build.log /app/
COPY --from=aot-build /workspace/native-version.txt /workspace/native-image.txt /workspace/runtime-image.txt /app/
RUN apt-get update && apt-get install -y --no-install-recommends python3 time \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "/benchmark/http_run.py"]
