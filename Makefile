QCC ?= qcc
QNX_VARIANT ?= gcc_ntox86_64

.PHONY: all clean

all: build/deadline

build/deadline: workload/deadline.c
	mkdir -p build
	$(QCC) -V$(QNX_VARIANT) -std=c11 -O2 -Wall -Wextra -Werror -pthread $< -o $@

clean:
	rm -f build/deadline
