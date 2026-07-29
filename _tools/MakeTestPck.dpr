program MakeTestPck;

{$APPTYPE CONSOLE}

uses
  System.SysUtils,
  uSiglus in '..\SPTranslate\uSiglus.pas';

type
  TPatch = record
    Index: Integer;
    Text: string;
  end;

  TPatcher = class
    procedure GetStrings(Sender: TObject; SceneIndex: Integer;
      var Strings: TStringArray);
    procedure Progress(Sender: TObject; Current, Total: Integer);
  end;

const
  TARGET_SCENE = 1;

var
  Patches: array of TPatch;

procedure TPatcher.GetStrings(Sender: TObject; SceneIndex: Integer;
  var Strings: TStringArray);
var
  I: Integer;
begin
  if SceneIndex <> TARGET_SCENE then
    Exit;
  for I := 0 to High(Patches) do
    if Patches[I].Index <= High(Strings) then
      Strings[Patches[I].Index] := EncodeRussian(Patches[I].Text);
end;

procedure TPatcher.Progress(Sender: TObject; Current, Total: Integer);
begin
  if (Current mod 150 = 0) or (Current = Total) then
    Writeln('  ', Current, ' / ', Total);
end;

procedure Add(AIndex: Integer; const AText: string);
begin
  SetLength(Patches, Length(Patches) + 1);
  Patches[High(Patches)].Index := AIndex;
  Patches[High(Patches)].Text := AText;
end;

var
  Pack, Check: TScenePack;
  P: TPatcher;
  S: TStringArray;
  SrcFile, DstFile: string;
  I: Integer;

begin
  try
    SrcFile := 'A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck.orig';
    DstFile := 'A:\Projects\Summer Pockets REFLECTION BLUE\Scene.pck';

    Add(4, 'Вдали начали проступать очертания острова.');
    Add(5, 'Динамики парома объявили о скором прибытии.');
    Add(6, 'Один за другим на палубу выходили пассажиры — ещё недавно она была ' +
           'в моём полном распоряжении.');
    Add(7, 'Диктор');
    Add(8, '«Паром прибывает на остров Торисиро, в порт города Торисиро».');
    Add(9, 'Объявление прозвучало ещё раз.');
    Add(10, 'Я снова перевёл взгляд на остров впереди.');
    Add(11, 'У подножия невысокой гряды, укрытой сплошной зеленью, вдоль берега ' +
            'редкой россыпью лепились крошечные крыши.');

    P := TPatcher.Create;
    Pack := TScenePack.Create;
    Check := TScenePack.Create;
    try
      Pack.LoadFromFile(SrcFile);
      Pack.OnGetStrings := P.GetStrings;
      Pack.OnProgress := P.Progress;
      Writeln('Scenes: ', Pack.Count);
      Writeln('Patches: ', Length(Patches));

      Writeln('Building...');
      Pack.BuildToFile(DstFile);

      Check.LoadFromFile(DstFile);
      S := Check.GetSceneStrings(TARGET_SCENE);
      Writeln('Verify (decoded back from carriers):');
      for I := 0 to High(Patches) do
        Writeln('  [', Patches[I].Index, '] ',
          DecodeRussian(S[Patches[I].Index]));
      Writeln('DONE');
    finally
      Check.Free;
      Pack.Free;
      P.Free;
    end;
  except
    on E: Exception do
      Writeln('ERROR: ', E.ClassName, ': ', E.Message);
  end;
end.
