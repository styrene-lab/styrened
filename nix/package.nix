{ python, deps, lib, version, src }:

python.pkgs.buildPythonApplication {
  pname = "styrened";
  inherit version;
  format = "pyproject";

  inherit src;

  nativeBuildInputs = with python.pkgs; [
    setuptools
    wheel
  ];

  propagatedBuildInputs = with python.pkgs; [
    deps.rns
    deps.lxmf
    pyyaml
    platformdirs
    sqlalchemy
    msgpack
  ];

  # Tests run separately via `make test` / `just test`
  doCheck = false;

  meta = with lib; {
    description = "Headless Styrene daemon for Reticulum mesh networks";
    homepage = "https://github.com/styrene-lab/styrened";
    license = licenses.mit;
    platforms = platforms.linux ++ platforms.darwin;
  };
}
