#!/usr/bin/bash

cd ~

mkdir -p ~/.config/
mkdir -p ~/.local/vim/{bak,tmp}

mkdir -p ~/pylib

for l in oil ; do
	rm -f ~/pylib/${l}
	ln -s /home/$(whoami)/python-${l}/src/ /home/$(whoami)/pylib/${l}
done

rsync -aPv ./weaver_api/home/ ~

