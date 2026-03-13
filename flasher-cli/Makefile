CGO_ENABLED := 0

.PHONY: build gui clean

build:
	CGO_ENABLED=$(CGO_ENABLED) go build -o flasher .

gui:
	CGO_ENABLED=1 CGO_CFLAGS="-I/usr/include/x86_64-linux-gnu" go build -o ../flasher-gui ./gui/

clean:
	rm -f flasher flasher-gui
