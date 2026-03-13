CGO_ENABLED := 0

.PHONY: build clean

build:
	CGO_ENABLED=$(CGO_ENABLED) go build -o flasher .

clean:
	rm -f flasher
