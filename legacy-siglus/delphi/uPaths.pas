{ Locates the repository and the game without hardcoded absolute paths.
  The root is found by walking up from the executable until AGENTS.md shows up,
  mirroring what game-tools/paths.py does on the Python side. }
unit uPaths;

interface

function RepoRoot: string;
function GameDir: string;
function ScenePck: string;
function ScenePckOrig: string;

implementation

uses
  System.SysUtils, System.IOUtils;

const
  { Mirrors game.install_dir in config/project.yaml. Delphi has no YAML reader
    here, so the value is duplicated on purpose; keep the two in step. }
  INSTALL_DIR = 'Summer Pockets REFLECTION BLUE';

function RepoRoot: string;
var
  Dir: string;
begin
  Dir := TPath.GetDirectoryName(ParamStr(0));
  while not TFile.Exists(TPath.Combine(Dir, 'AGENTS.md')) do
  begin
    if TPath.GetPathRoot(Dir) = Dir then
      raise Exception.Create('Repository root not found above ' + ParamStr(0));
    Dir := TPath.GetDirectoryName(Dir);
  end;
  Result := Dir;
end;

function GameDir: string;
begin
  Result := TPath.Combine(RepoRoot, INSTALL_DIR);
  if not TDirectory.Exists(Result) then
    raise Exception.Create('Game not found at ' + Result);
end;

function ScenePck: string;
begin
  Result := TPath.Combine(GameDir, 'Scene.pck');
end;

function ScenePckOrig: string;
begin
  Result := TPath.Combine(GameDir, 'Scene.pck.orig');
end;

end.
