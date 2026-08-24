{
  description = "Reproducible NHK Radio CI runtime";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      mkPkgs = system: import nixpkgs { inherit system; };
      mkYtDlp = pkgs:
        let
          python3Packages = pkgs.python312Packages;
          # Native HLS needs neither curl impersonation nor OS keyring support.
          baseApplication = pkgs.yt-dlp-light.override { inherit python3Packages; };
          application = baseApplication.overridePythonAttrs (previous: {
            dependencies = builtins.filter
              (dependency: !builtins.elem (dependency.pname or "") [ "curl-cffi" "secretstorage" ])
              previous.dependencies;
          });
        in
        python3Packages.toPythonModule application;
      mkPython = pkgs: with pkgs.python312Packages; pkgs.python312.withPackages (_: [
        httpx
        pyyaml
        pycryptodomex
        (mkYtDlp pkgs)
      ]);
      mkCheckPython = pkgs: with pkgs.python312Packages; pkgs.python312.withPackages (_: [
        httpx
        pyyaml
        pycryptodomex
        pytest
        (mkYtDlp pkgs)
      ]);
      mkRuntimeImage = pkgs:
        let
          python = mkPython pkgs;
          openvpn = pkgs.openvpn.override { useSystemd = false; };
          root = pkgs.buildEnv {
            name = "nhk-radio-runtime-root";
            paths = [
              pkgs.cacert
              pkgs.coreutils
              pkgs.ffmpeg-headless
              pkgs.iproute2
              openvpn
              python
              pkgs.tzdata
            ];
            pathsToLink = [ "/bin" "/etc" "/share" ];
          };
        in
        pkgs.dockerTools.buildLayeredImage {
          name = "nhk-radio-runtime";
          tag = "local";
          created = "1970-01-01T00:00:01Z";
          contents = root;
          extraCommands = ''
            mkdir -p app/data run tmp work
            cp -R ${./nhk_recorder} app/nhk_recorder
          '';
          config = {
            Env = [
              "HOME=/tmp"
              "LANG=C.UTF-8"
              "PATH=/bin"
              "PYTHONPATH=/app"
              "PYTHONDONTWRITEBYTECODE=1"
              "PYTHONUNBUFFERED=1"
              "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
              "TZ=Asia/Tokyo"
              "TZDIR=/share/zoneinfo"
            ];
            WorkingDir = "/work";
          };
        };
    in
    {
      packages = forAllSystems (system:
        let pkgs = mkPkgs system;
        in nixpkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
          default = mkRuntimeImage pkgs;
          runtime-image = mkRuntimeImage pkgs;
        });

      checks = forAllSystems (system:
        let
          pkgs = mkPkgs system;
          python = mkCheckPython pkgs;
          runtimePython = mkPython pkgs;
          common = {
            unit = pkgs.runCommand "nhk-radio-unit-tests" {
              nativeBuildInputs = [ python ];
            } ''
              export HOME="$TMPDIR/home"
              mkdir -p "$HOME" source
              cp -R ${./nhk_recorder} source/nhk_recorder
              cp -R ${./tests} source/tests
              chmod -R u+w source
              cd source
              PYTHONPATH="$PWD" pytest -q
              touch "$out"
            '';

            workflows = pkgs.runCommand "nhk-radio-workflow-lint" {
              nativeBuildInputs = [ pkgs.actionlint pkgs.shellcheck ];
            } ''
              mkdir -p source/.github/workflows source/scripts
              cp ${./.github/workflows}/*.yml source/.github/workflows/
              cp ${./scripts/network-namespace-smoke.sh} source/scripts/network-namespace-smoke.sh
              chmod -R u+w source
              cd source
              actionlint -shellcheck=shellcheck .github/workflows/*.yml
              shellcheck scripts/network-namespace-smoke.sh
              touch "$out"
            '';
          };
        in common // nixpkgs.lib.optionalAttrs pkgs.stdenv.isLinux {
          runtime-smoke = pkgs.runCommand "nhk-radio-runtime-smoke" {
            nativeBuildInputs = [
              runtimePython
              pkgs.ffmpeg-headless
              pkgs.iproute2
              (pkgs.openvpn.override { useSystemd = false; })
            ];
          } ''
            export TZDIR=${pkgs.tzdata}/share/zoneinfo
            python -c 'import httpx, yaml, Cryptodome; from zoneinfo import ZoneInfo; ZoneInfo("Asia/Tokyo")'
            PYTHONPATH=${./.} python -m nhk_recorder --help >/dev/null
            yt-dlp --version >/dev/null
            ffmpeg -version >/dev/null
            ffprobe -version >/dev/null
            ip -Version >/dev/null
            openvpn --version >/dev/null
            touch "$out"
          '';
          runtime-image = mkRuntimeImage pkgs;
        });

      devShells = forAllSystems (system:
        let pkgs = mkPkgs system;
        in {
          default = pkgs.mkShell {
            packages = [
              (mkCheckPython pkgs)
              pkgs.actionlint
              pkgs.ffmpeg-headless
              pkgs.openvpn
              pkgs.shellcheck
            ];
          };
        });
    };
}
