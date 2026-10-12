RUNS ?= 30
WARMUPS ?= 2
ITERATIONS ?= 100000
TRAIN_ITERATIONS ?= 100000
TRAIN_REQUESTS ?= 200
PORT ?= 8080
SUITE ?= startup
LOAD_RUNS ?= 5
LOAD_WARMUP ?= 30
LOAD_SECONDS ?= 60
RATE ?= 100
export TRAIN_ITERATIONS TRAIN_REQUESTS PORT
EXAMPLE_DIR_01 := 01-plain-java
EXAMPLE_DIR_02 := 02-plain-jvm-aot-cache
EXAMPLE_DIR_03 := 03-plain-graalvm-native
EXAMPLE_DIR_04 := 04-spring-java-baseline
EXAMPLE_DIR_05 := 05-spring-aot-cache
EXAMPLE_DIR_06 := 06-spring-jvm-aot-cache
EXAMPLE_DIR_07 := 07-spring-aot-graalvm-native
EXAMPLE_DIR_08 := 08-spring-aot-jvm-aot-cache
EXAMPLE_DIR_09 := 09-combined-comparison
EXAMPLES := $(EXAMPLE_DIR_01) $(EXAMPLE_DIR_02) $(EXAMPLE_DIR_03) $(EXAMPLE_DIR_04) $(EXAMPLE_DIR_05) $(EXAMPLE_DIR_06) $(EXAMPLE_DIR_07) $(EXAMPLE_DIR_08) $(EXAMPLE_DIR_09)
CACHE_EXAMPLES := $(EXAMPLE_DIR_02) $(EXAMPLE_DIR_06) $(EXAMPLE_DIR_08) $(EXAMPLE_DIR_09)
EXAMPLE_TARGETS := status validate build train verify test-app bench clean
.DEFAULT_GOAL := help

.PHONY: help $(EXAMPLE_TARGETS)

help:
	@printf '%s\n' \
	  'make status       Check Docker Compose and the selected toolchains' \
	  'make validate     Validate the Compose configuration' \
	  'make build        Build the selected example (runs Java tests)' \
	  'make train        Select a cache example and build its caches' \
	  'make verify       Select a cache example and verify cache use/invalid deployments' \
	  'make test-app     Build and run the CLI, or start an HTTP app and check its API (01-08)' \
	  'make bench        Measure fresh processes, print a table, and save a report' \
	  'make clean        Remove this project containers and network' \
	  '' \
	  'Example commands open fzf; Enter selects, Esc cancels. make help needs no selection.' \
	  'Skip the picker: EXAMPLE=01|02|03|04|05|06|07|08|09 or a full example directory name' \
	  'Example 08 runs Spring AOT + JVM cache; example 09 is a comparison suite (make bench)' \
	  'Options: RUNS=10 WARMUPS=2 ITERATIONS=100000 TRAIN_ITERATIONS=100000 TRAIN_REQUESTS=200' \
	  'HTTP options: PORT=8080 SUITE=startup|load|all LOAD_RUNS=5 LOAD_WARMUP=30 LOAD_SECONDS=60 RATE=100'

ifeq ($(strip $(EXAMPLE)),)
REQUESTED_TARGETS := $(filter $(EXAMPLE_TARGETS),$(MAKECMDGOALS))
PICKER_EXAMPLES := $(if $(filter train verify,$(REQUESTED_TARGETS)),$(CACHE_EXAMPLES),$(EXAMPLES))
ifneq ($(filter test-app,$(REQUESTED_TARGETS)),)
PICKER_EXAMPLES := $(filter-out $(EXAMPLE_DIR_09),$(PICKER_EXAMPLES))
endif
.PHONY: select-example
$(EXAMPLE_TARGETS): select-example

select-example:
	@selected=$$(sh scripts/select-example.sh '$(REQUESTED_TARGETS)' $(PICKER_EXAMPLES)) || exit $$?; \
	  $(MAKE) --no-print-directory $(REQUESTED_TARGETS) EXAMPLE="$$selected"
else
EXAMPLE_DIR := $(if $(EXAMPLE_DIR_$(EXAMPLE)),$(EXAMPLE_DIR_$(EXAMPLE)),$(filter $(EXAMPLE),$(EXAMPLES)))
ifeq ($(EXAMPLE_DIR),)
$(error Unknown EXAMPLE '$(EXAMPLE)'; use 01 through 09 or an example directory name)
endif
EXAMPLE_NUMBER := $(firstword $(subst -, ,$(EXAMPLE_DIR)))
COMPOSE := docker compose -f examples/$(EXAMPLE_DIR)/compose.yaml
APPLICATION_SERVICE_01 := cli-baseline
APPLICATION_SERVICE_02 := cli-jvm-cache
APPLICATION_SERVICE_03 := cli-native
APPLICATION_SERVICE_04 := spring-baseline
APPLICATION_SERVICE_05 := spring-aot
APPLICATION_SERVICE_06 := spring-jvm-cache
APPLICATION_SERVICE_07 := spring-native
APPLICATION_SERVICE_08 := spring-combined
APPLICATION_SERVICE := $(APPLICATION_SERVICE_$(EXAMPLE_NUMBER))
SPRING_EXAMPLE := $(filter 04 05 06 07 08 09,$(EXAMPLE_NUMBER))
BENCH_SERVICE := $(if $(SPRING_EXAMPLE),http-benchmark,cli-benchmark)
CACHE_SCRIPT_02 := cache_check.py
CACHE_SCRIPT_06 := http_cache_check.py
CACHE_SCRIPT_08 := http_cache_check.py
CACHE_SCRIPT_09 := http_cache_check.py
BUILD_SERVICE := $(if $(APPLICATION_SERVICE),$(APPLICATION_SERVICE),$(BENCH_SERVICE))
CACHE_BUILD_SERVICE := $(if $(APPLICATION_SERVICE),$(APPLICATION_SERVICE),spring-combined)
BENCH_OPTIONS_02 := --compare
BENCH_OPTIONS_03 := --compare
HTTP_BENCH_OPTIONS := $(if $(SPRING_EXAMPLE),--suite $(SUITE) --load-runs $(LOAD_RUNS) --load-warmup $(LOAD_WARMUP) --load-seconds $(LOAD_SECONDS) --rate $(RATE))
BENCH_TERMINAL_OPTIONS := --env TERM --env NO_COLOR --env FORCE_COLOR --env REPORT_HOST_RESULTS="$$(pwd)/results"

status:
	docker version
	$(COMPOSE) version
	$(COMPOSE) --profile tools run --rm --no-deps jdk java -version
	@if [ -n '$(filter 03 07 09,$(EXAMPLE_NUMBER))' ]; then $(COMPOSE) --profile tools run --rm --no-deps native-toolchain --version; fi

validate:
	$(COMPOSE) config --quiet

build: validate
	$(COMPOSE) build $(BUILD_SERVICE)

train: validate
	@test -n '$(filter $(EXAMPLE_DIR),$(CACHE_EXAMPLES))' || { printf '%s\n' 'Cache training requires EXAMPLE=02, EXAMPLE=06, EXAMPLE=08 or EXAMPLE=09'; exit 2; }
	$(COMPOSE) build $(CACHE_BUILD_SERVICE)

verify: validate
	@test -n '$(filter $(EXAMPLE_DIR),$(CACHE_EXAMPLES))' || { printf '%s\n' 'Cache verification requires EXAMPLE=02, EXAMPLE=06, EXAMPLE=08 or EXAMPLE=09'; exit 2; }
	$(COMPOSE) build $(BENCH_SERVICE)
	$(COMPOSE) --profile benchmark run --rm --no-deps --entrypoint python3 $(BENCH_SERVICE) /benchmark/$(CACHE_SCRIPT_$(EXAMPLE_NUMBER))

ifeq ($(EXAMPLE_NUMBER),09)
test-app:
	@printf '%s\n' 'Example 09 is a comparison suite. Use make bench EXAMPLE=09 (or SUITE=all for HTTP load).' >&2; exit 2
else
test-app: validate
ifneq ($(SPRING_EXAMPLE),)
	$(COMPOSE) --profile $(APPLICATION_SERVICE) up --build --detach --wait $(APPLICATION_SERVICE)
	$(COMPOSE) build $(BENCH_SERVICE)
	@published_address=$$($(COMPOSE) port $(APPLICATION_SERVICE) 8080) || exit $$?; \
	  $(COMPOSE) --profile benchmark run --rm --no-deps --entrypoint python3 $(BENCH_SERVICE) /benchmark/http_test_app.py --example $(EXAMPLE_DIR) --host $(APPLICATION_SERVICE) --display-url "http://localhost:$${published_address##*:}" --iterations $(ITERATIONS) || exit $$?; \
	  printf 'Ready: http://localhost:%s/ready\nStop: make clean EXAMPLE=%s\n\n' "$${published_address##*:}" '$(EXAMPLE_NUMBER)'
else
	$(COMPOSE) --profile $(APPLICATION_SERVICE) run --rm --build $(APPLICATION_SERVICE) --iterations $(ITERATIONS)
endif
endif

bench: validate
	@mkdir -p results
ifneq ($(SPRING_EXAMPLE),)
	$(COMPOSE) build http-benchmark
	@trap '$(COMPOSE) stop http-load-client >/dev/null 2>&1' EXIT; \
	  $(COMPOSE) --profile benchmark run --rm --use-aliases $(BENCH_TERMINAL_OPTIONS) http-benchmark --runs $(RUNS) --warmups $(WARMUPS) --iterations $(ITERATIONS) $(HTTP_BENCH_OPTIONS)
else
	$(COMPOSE) --profile benchmark run --rm --build $(BENCH_TERMINAL_OPTIONS) $(BENCH_SERVICE) $(BENCH_OPTIONS_$(EXAMPLE_NUMBER)) --runs $(RUNS) --warmups $(WARMUPS) --iterations $(ITERATIONS) $(HTTP_BENCH_OPTIONS)
endif

clean:
	$(COMPOSE) --profile "*" down --remove-orphans
endif
