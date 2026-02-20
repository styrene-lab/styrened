{
  description = "Styrened - Headless Styrene daemon for Reticulum mesh networks";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    nix2container = {
      url = "github:nlewo/nix2container";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, nix2container }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python311;

        version = builtins.replaceStrings [ "\n" ] [ "" ]
          (builtins.readFile ./VERSION);

        commitSha =
          if self ? shortRev then self.shortRev
          else if self ? dirtyShortRev then self.dirtyShortRev
          else "unknown";

        deps = import ./nix/deps.nix {
          inherit python;
          inherit (pkgs) fetchurl lib;
        };

        src = pkgs.lib.cleanSource ./.;

        styrened = import ./nix/package.nix {
          inherit python deps version src;
          inherit (pkgs) lib;
        };

        entrypoint = pkgs.writeShellApplication {
          name = "entrypoint";
          runtimeInputs = [ pkgs.coreutils python styrened ];
          text = builtins.readFile ./container/entrypoint.sh;
        };

        images = pkgs.lib.optionalAttrs pkgs.stdenv.isLinux (
          import ./nix/oci.nix {
            inherit nix2container pkgs python deps styrened entrypoint version commitSha;
          }
        );
      in
      {
        packages = {
          default = styrened;
        } // pkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
          oci = images.oci;
          oci-test = images.oci-test;
        };

        apps.default = {
          type = "app";
          program = "${styrened}/bin/styrened";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            python.pkgs.hatchling
            python.pkgs.pytest
            python.pkgs.pytest-asyncio
            python.pkgs.mypy
            python.pkgs.ruff
            pkgs.just
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
