CGO_ENABLED := 0

.PHONY: build gui clean

build:
	CGO_ENABLED=$(CGO_ENABLED) go build -o flasher .

gui:
	CGO_ENABLED=1 go build -o flasher-gui ./gui/

clean:
	rm -f flasher flasher-gui
