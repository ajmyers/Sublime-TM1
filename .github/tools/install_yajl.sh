#!/bin/sh

install_unix() {
	mkdir cextern/yajl/build; cd cextern/yajl/build
	cmake .. -DCMAKE_C_FLAGS="-O3"
	make all -j 4
	make install
}

OS="`uname -s`"
echo "Building libyajl on $OS"
case "$OS" in
	MSYS_*|MINGW_*)
		echo "No extra step required in Windows"
		;;
	Darwin|Linux)
		install_unix
		;;
esac

