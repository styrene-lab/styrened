{ python, fetchurl, lib }:
let
  inherit (python.pkgs) buildPythonPackage fetchPypi;

  rns = buildPythonPackage rec {
    pname = "rns";
    version = "1.1.3";
    format = "setuptools";

    src = fetchPypi {
      inherit pname version;
      hash = "sha256-zS4aHb4N2MVpGzx6AdI9BgmBsSeqcQAdDVltZT6fPuo=";
    };

    propagatedBuildInputs = with python.pkgs; [
      cryptography
      pyserial
    ];

    # RNS tests require network access
    doCheck = false;

    pythonImportsCheck = [ "RNS" ];

    meta = with lib; {
      description = "Reticulum Network Stack";
      homepage = "https://reticulum.network";
      license = licenses.mit;
    };
  };

  lxmf = buildPythonPackage rec {
    pname = "lxmf";
    version = "0.9.4";
    format = "wheel";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/3b/b1/1f06fdfe6e6366781625802102b77180645fc9c04a358bc899ace7a07e31/lxmf-0.9.4-py3-none-any.whl";
      hash = "sha256-ct66zoAd7IsshB7jR1/ONrewDqjiWYIuFVV9393B5GQ=";
    };

    propagatedBuildInputs = [ rns ];

    # LXMF tests require network access
    doCheck = false;

    pythonImportsCheck = [ "LXMF" ];

    meta = with lib; {
      description = "Lightweight Extensible Message Format for Reticulum";
      homepage = "https://reticulum.network";
      license = licenses.mit;
    };
  };
in
{ inherit rns lxmf; }
