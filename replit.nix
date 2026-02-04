{ pkgs }: {
  deps = [
    pkgs.python3
    pkgs.python3Packages.pip
    pkgs.ffmpeg
    pkgs.git
  ];
  
  env = {
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.ffmpeg
      pkgs.stdenv.cc.cc.lib
    ];
  };
}
