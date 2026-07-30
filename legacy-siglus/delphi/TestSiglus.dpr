program TestSiglus;

{$APPTYPE CONSOLE}

uses
  System.SysUtils,
  System.IOUtils,
  uSiglus in '..\SPTranslate\uSiglus.pas',
  uPaths in 'uPaths.pas';

var
  Pack, Pack2: TScenePack;
  A, B: TStringArray;
  I, J, Mismatch, TotalStrings: Integer;
  SrcFile, OutFile: string;

begin
  try
    SrcFile := ScenePck;
    OutFile := TPath.Combine(TPath.GetTempPath, 'Scene.rebuilt.pck');

    Pack := TScenePack.Create;
    Pack2 := TScenePack.Create;
    try
      Writeln('Loading ', SrcFile);
      Pack.LoadFromFile(SrcFile);
      Writeln('Scenes: ', Pack.Count);
      Writeln('Scene[1] name length: ', Length(Pack.SceneNames[1]));

      A := Pack.GetSceneStrings(1);
      Writeln('Scene[1] strings: ', Length(A));
      Writeln('Scene[1] string[0]: ', A[0]);

      Writeln('Rebuilding to ', OutFile);
      Pack.BuildToFile(OutFile);

      Pack2.LoadFromFile(OutFile);
      Writeln('Rebuilt scenes: ', Pack2.Count);
      if Pack2.Count <> Pack.Count then
        raise Exception.Create('scene count changed');

      Mismatch := 0;
      TotalStrings := 0;
      for I := 0 to Pack.Count - 1 do
      begin
        A := Pack.GetSceneStrings(I);
        B := Pack2.GetSceneStrings(I);
        if Length(A) <> Length(B) then
        begin
          Writeln('scene ', I, ': count ', Length(A), ' -> ', Length(B));
          Inc(Mismatch);
          Continue;
        end;
        Inc(TotalStrings, Length(A));
        for J := 0 to Length(A) - 1 do
          if A[J] <> B[J] then
          begin
            Inc(Mismatch);
            if Mismatch < 5 then
              Writeln('scene ', I, ' str ', J, ' differs');
          end;
        if Pack.SceneNames[I] <> Pack2.SceneNames[I] then
        begin
          Writeln('scene ', I, ': name differs');
          Inc(Mismatch);
        end;
      end;
      Writeln('Compared strings: ', TotalStrings);
      Writeln('Mismatches: ', Mismatch);
      if Mismatch = 0 then
        Writeln('ROUND TRIP OK')
      else
        Writeln('ROUND TRIP FAILED');
    finally
      Pack.Free;
      Pack2.Free;
    end;
  except
    on E: Exception do
      Writeln('ERROR: ', E.ClassName, ': ', E.Message);
  end;
end.
