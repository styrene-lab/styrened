{ nix2container, pkgs, python, deps, styrened, entrypoint, version, commitSha }:
let
  n2c = nix2container.packages.${pkgs.system}.nix2container;

  # Minimal root filesystem for the container
  initDirs = pkgs.runCommand "container-init" {} ''
    mkdir -p $out/tmp $out/app $out/config $out/data $out/etc
    cat > $out/etc/passwd <<'PASSWD'
    root:x:0:0:root:/app:/bin/sh
    nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
    PASSWD
    cat > $out/etc/group <<'GROUP'
    root:x:0:
    nogroup:x:65534:
    GROUP
  '';

  # Shared dependency list (single source of truth for layer 2 and package.nix)
  runtimeDeps = [
    deps.rns
    deps.lxmf
    python.pkgs.pyyaml
    python.pkgs.platformdirs
    python.pkgs.sqlalchemy
    python.pkgs.msgpack
  ];
in
{
  oci = n2c.buildImage {
    name = "ghcr.io/styrene-lab/styrened";
    tag = version;

    config = {
      entrypoint = [ "${entrypoint}/bin/entrypoint" ];
      cmd = [ "${styrened}/bin/styrened" ];
      env = [
        "HOME=/app"
        "XDG_CONFIG_HOME=/config"
        "XDG_DATA_HOME=/data"
        "PYTHONUNBUFFERED=1"
        "RNS_LOGLEVEL=4"
        "STYRENE_CONFIG_DIR=/config"
        "STYRENE_VERSION=${version}"
      ];
      labels = {
        "org.opencontainers.image.version" = version;
        "org.opencontainers.image.revision" = commitSha;
        "org.opencontainers.image.title" = "styrened";
        "org.opencontainers.image.description" = "Headless Styrene daemon for Reticulum mesh networks";
        "org.opencontainers.image.source" = "https://github.com/styrene-lab/styrened";
        "org.opencontainers.image.licenses" = "MIT";
      };
    };

    copyToRoot = [ initDirs ];

    layers = [
      # Layer 1: Python runtime (changes rarely)
      (n2c.buildLayer { deps = [ python ]; })
      # Layer 2: Dependencies (changes on dep bumps)
      (n2c.buildLayer { deps = runtimeDeps; })
      # Layer 3: styrened + entrypoint (changes on code changes)
      (n2c.buildLayer { deps = [ styrened entrypoint pkgs.coreutils ]; })
    ];
  };

  oci-test = n2c.buildImage {
    name = "ghcr.io/styrene-lab/styrened-test";
    tag = version;

    config = {
      entrypoint = [ "${entrypoint}/bin/entrypoint" ];
      cmd = [ "${styrened}/bin/styrened" ];
      env = [
        "HOME=/app"
        "XDG_CONFIG_HOME=/config"
        "XDG_DATA_HOME=/data"
        "PYTHONUNBUFFERED=1"
        "RNS_LOGLEVEL=4"
        "STYRENE_CONFIG_DIR=/config"
        "STYRENE_VERSION=${version}"
      ];
      labels = {
        "org.opencontainers.image.version" = version;
        "org.opencontainers.image.revision" = commitSha;
        "org.opencontainers.image.title" = "styrened-test";
        "org.opencontainers.image.description" = "Styrened test image with pytest and diagnostic tools";
        "org.opencontainers.image.source" = "https://github.com/styrene-lab/styrened";
        "org.opencontainers.image.licenses" = "MIT";
      };
    };

    copyToRoot = [ initDirs ];

    layers = [
      # Layer 1: Python runtime (changes rarely)
      (n2c.buildLayer { deps = [ python ]; })
      # Layer 2: Dependencies (changes on dep bumps)
      (n2c.buildLayer { deps = runtimeDeps; })
      # Layer 3: styrened + entrypoint (changes on code changes)
      (n2c.buildLayer { deps = [ styrened entrypoint pkgs.coreutils ]; })
      # Layer 4: Test tools
      (n2c.buildLayer { deps = [
        python.pkgs.pytest
        python.pkgs.pytest-asyncio
        pkgs.iputils    # ping
        pkgs.procps     # ps
      ]; })
    ];
  };
}
