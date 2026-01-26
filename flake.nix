{
  description = "Styrened - Headless Styrene daemon for Reticulum mesh networks";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python311;

        # TODO: Package styrene-core for Nix
        # For now, this flake assumes styrene-core is available

        styrened = python.pkgs.buildPythonApplication {
          pname = "styrened";
          version = "0.1.0";
          format = "pyproject";

          src = ./.;

          nativeBuildInputs = with python.pkgs; [
            setuptools
            wheel
          ];

          propagatedBuildInputs = with python.pkgs; [
            # styrene-core  # TODO: Add when packaged
            # For now, list direct dependencies:
            # rns lxmf pyyaml platformdirs sqlalchemy msgpack
          ];

          # Skip tests for now (need styrene-core)
          doCheck = false;

          meta = with pkgs.lib; {
            description = "Headless Styrene daemon for edge deployments";
            homepage = "https://github.com/styrene-lab/styrened";
            license = licenses.mit;
            maintainers = [ ];
            platforms = platforms.linux ++ platforms.darwin;
          };
        };
      in
      {
        packages.default = styrened;

        apps.default = {
          type = "app";
          program = "${styrened}/bin/styrened";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            python.pkgs.setuptools
            python.pkgs.wheel
            python.pkgs.pytest
            python.pkgs.mypy
            python.pkgs.ruff
          ];
        };
      }
    ) // {
      # NixOS module for systemd service
      nixosModules.default = { config, lib, pkgs, ... }:
        with lib;
        let
          cfg = config.services.styrened;
        in {
          options.services.styrened = {
            enable = mkEnableOption "Styrene daemon";

            package = mkOption {
              type = types.package;
              default = self.packages.${pkgs.system}.default;
              description = "The styrened package to use";
            };

            user = mkOption {
              type = types.str;
              default = "styrened";
              description = "User to run styrened as";
            };

            group = mkOption {
              type = types.str;
              default = "styrened";
              description = "Group to run styrened as";
            };
          };

          config = mkIf cfg.enable {
            users.users.${cfg.user} = {
              isSystemUser = true;
              group = cfg.group;
              description = "Styrene daemon user";
              home = "/var/lib/styrened";
              createHome = true;
            };

            users.groups.${cfg.group} = {};

            systemd.services.styrened = {
              description = "Styrene mesh network daemon";
              wantedBy = [ "multi-user.target" ];
              after = [ "network.target" ];

              serviceConfig = {
                Type = "simple";
                User = cfg.user;
                Group = cfg.group;
                ExecStart = "${cfg.package}/bin/styrened";
                Restart = "always";
                RestartSec = "10s";

                # Hardening
                PrivateTmp = true;
                ProtectSystem = "strict";
                ProtectHome = true;
                NoNewPrivileges = true;
                ReadWritePaths = [ "/var/lib/styrened" ];
              };
            };
          };
        };
    };
}
