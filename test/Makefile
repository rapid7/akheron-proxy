all: port-runner

port-runner: port-runner.c
	gcc $^ -lpthread -o $@

clean:
	rm -f *.o port-runner
