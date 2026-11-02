{
  description = "Your Turn: a local inbox for your coding agents";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      project = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project;
    in
    {
      packages = forAllSystems (pkgs: rec {
        your-turn = pkgs.python3Packages.buildPythonApplication {
          pname = project.name;
          inherit (project) version;
          pyproject = true;
          src = ./.;

          build-system = [ pkgs.python3Packages.hatchling ];
          dependencies = with pkgs.python3Packages; [ fastapi uvicorn ];

          nativeCheckInputs = with pkgs.python3Packages; [ pytestCheckHook httpx ];
          preCheck = "export HOME=$(mktemp -d)";
          # Both expect a source checkout: config.toml beside src/, and the uv-managed .venv.
          disabledTests = [
            "test_checkout_config_does_not_depend_on_working_directory"
            "test_demo_server_never_rewrites_user_inbox_state"
          ];
          pythonImportsCheck = [ "yourturn" ];

          meta = {
            inherit (project) description;
            homepage = "https://github.com/martin-gomola/your-turn";
            license = pkgs.lib.licenses.mit;
            mainProgram = "your-turn";
          };
        };
        default = your-turn;
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.python3 pkgs.uv pkgs.nodejs ];
        };
      });
    };
}
