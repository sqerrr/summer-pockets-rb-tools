unit uMain;

interface

uses
  Winapi.Windows, Winapi.Messages, System.SysUtils, System.Classes,
  System.Generics.Collections, System.StrUtils, System.Character, System.UITypes,
  Vcl.Graphics, Vcl.Controls, Vcl.Forms, Vcl.Dialogs, Vcl.StdCtrls,
  Vcl.ComCtrls, Vcl.ExtCtrls, Vcl.Themes,
  uSiglus;

type
  TfrmMain = class(TForm)
    pnlTop: TPanel;
    btnOpenPck: TButton;
    btnLoadProj: TButton;
    btnSaveProj: TButton;
    btnBuild: TButton;
    lblStats: TLabel;
    sbMain: TStatusBar;
    pnlLeft: TPanel;
    pnlSceneFilter: TPanel;
    edtSceneFilter: TEdit;
    lstScenes: TListBox;
    splLeft: TSplitter;
    pnlMain: TPanel;
    pnlFilter: TPanel;
    edtFilter: TEdit;
    chkOnlyText: TCheckBox;
    chkOnlyUntranslated: TCheckBox;
    lblRows: TLabel;
    pnlEdit: TPanel;
    pnlEditButtons: TPanel;
    btnApply: TButton;
    btnCopyOrig: TButton;
    btnPrev: TButton;
    btnNext: TButton;
    lblHint: TLabel;
    gbOrig: TGroupBox;
    memoOrig: TMemo;
    splEdit: TSplitter;
    gbTrans: TGroupBox;
    memoTrans: TMemo;
    splMain: TSplitter;
    lvStrings: TListView;
    procedure FormCreate(Sender: TObject);
    procedure FormDestroy(Sender: TObject);
    procedure FormCloseQuery(Sender: TObject; var CanClose: Boolean);
    procedure btnOpenPckClick(Sender: TObject);
    procedure btnLoadProjClick(Sender: TObject);
    procedure btnSaveProjClick(Sender: TObject);
    procedure btnBuildClick(Sender: TObject);
    procedure edtSceneFilterChange(Sender: TObject);
    procedure lstScenesClick(Sender: TObject);
    procedure edtFilterChange(Sender: TObject);
    procedure lvStringsData(Sender: TObject; Item: TListItem);
    procedure lvStringsSelectItem(Sender: TObject; Item: TListItem;
      Selected: Boolean);
    procedure btnApplyClick(Sender: TObject);
    procedure btnCopyOrigClick(Sender: TObject);
    procedure btnPrevClick(Sender: TObject);
    procedure btnNextClick(Sender: TObject);
    procedure memoTransKeyDown(Sender: TObject; var Key: Word;
      Shift: TShiftState);
  private
    FPack: TScenePack;
    FTrans: TDictionary<string, string>;
    FSceneMap: TArray<Integer>;
    FOrig: TStringArray;
    FRows: TArray<Integer>;
    FCurScene: Integer;
    FCurRow: Integer;
    FProjFile: string;
    FDirty: Boolean;
    FLoading: Boolean;
    function TransKey(ASceneIndex, AStringIndex: Integer): string;
    function GetTranslation(ASceneIndex, AStringIndex: Integer): string;
    procedure SetTranslation(ASceneIndex, AStringIndex: Integer; const AValue: string);
    procedure RefreshSceneList;
    procedure RefreshRows;
    procedure ShowRow(ARow: Integer);
    procedure ApplyPendingEdit;
    procedure UpdateStats;
    procedure SetDirty(AValue: Boolean);
    function AskSaveProject: Boolean;
    procedure PackProgress(Sender: TObject; Current, Total: Integer);
    procedure PackGetStrings(Sender: TObject; SceneIndex: Integer;
      var Strings: TStringArray);
  end;

var
  frmMain: TfrmMain;

implementation

{$R *.dfm}

const
  KEY_SEP = #1;

{ Collapses control characters so a string fits into one grid line. }
function Flatten(const S: string): string;
var
  I: Integer;
  SB: TStringBuilder;
begin
  SB := TStringBuilder.Create(Length(S) + 8);
  try
    for I := 1 to Length(S) do
      case S[I] of
        #13: ;
        #10: SB.Append('\n');
        #9: SB.Append('\t');
      else
        SB.Append(S[I]);
      end;
    Result := SB.ToString;
  finally
    SB.Free;
  end;
end;

function Escape(const S: string): string;
var
  I: Integer;
  SB: TStringBuilder;
begin
  SB := TStringBuilder.Create(Length(S) + 8);
  try
    for I := 1 to Length(S) do
      case S[I] of
        '\': SB.Append('\\');
        #13: SB.Append('\r');
        #10: SB.Append('\n');
        #9: SB.Append('\t');
      else
        SB.Append(S[I]);
      end;
    Result := SB.ToString;
  finally
    SB.Free;
  end;
end;

function Unescape(const S: string): string;
var
  I: Integer;
  SB: TStringBuilder;
begin
  SB := TStringBuilder.Create(Length(S));
  try
    I := 1;
    while I <= Length(S) do
    begin
      if (S[I] = '\') and (I < Length(S)) then
      begin
        Inc(I);
        case S[I] of
          'n': SB.Append(#10);
          'r': SB.Append(#13);
          't': SB.Append(#9);
          '\': SB.Append('\');
        else
          SB.Append(S[I]);
        end;
      end
      else
        SB.Append(S[I]);
      Inc(I);
    end;
    Result := SB.ToString;
  finally
    SB.Free;
  end;
end;

{ Rough filter that hides asset names, labels and other identifiers. }
function LooksLikeText(const S: string): Boolean;
var
  I: Integer;
  HasSpace, HasCJK, HasLetter: Boolean;
begin
  if Length(S) < 3 then
    Exit(False);
  HasSpace := False;
  HasCJK := False;
  HasLetter := False;
  for I := 1 to Length(S) do
  begin
    if S[I] = ' ' then
      HasSpace := True
    else if (S[I] >= #$3040) and (S[I] <= #$9FFF) then
      HasCJK := True
    else if S[I].IsLetter then
      HasLetter := True;
  end;
  Result := HasCJK or (HasSpace and HasLetter);
end;

{ TfrmMain }

procedure TfrmMain.FormCreate(Sender: TObject);
begin
  FPack := TScenePack.Create;
  FPack.OnProgress := PackProgress;
  FPack.OnGetStrings := PackGetStrings;
  FTrans := TDictionary<string, string>.Create;
  FCurScene := -1;
  FCurRow := -1;
  UpdateStats;
end;

procedure TfrmMain.FormDestroy(Sender: TObject);
begin
  FTrans.Free;
  FPack.Free;
end;

procedure TfrmMain.FormCloseQuery(Sender: TObject; var CanClose: Boolean);
begin
  ApplyPendingEdit;
  CanClose := AskSaveProject;
end;

function TfrmMain.AskSaveProject: Boolean;
begin
  Result := True;
  if not FDirty then
    Exit;
  case MessageDlg('Перевод изменён. Сохранить?', mtConfirmation,
    [mbYes, mbNo, mbCancel], 0) of
    mrYes:
      begin
        btnSaveProjClick(nil);
        Result := not FDirty;
      end;
    mrNo:
      Result := True;
  else
    Result := False;
  end;
end;

procedure TfrmMain.SetDirty(AValue: Boolean);
begin
  FDirty := AValue;
  if FProjFile <> '' then
    Caption := 'SP RB Translator - ' + ExtractFileName(FProjFile)
  else
    Caption := 'SP RB Translator';
  if FDirty then
    Caption := Caption + ' *';
end;

function TfrmMain.TransKey(ASceneIndex, AStringIndex: Integer): string;
begin
  { Keyed by scene name, so the project survives a different pack ordering. }
  Result := FPack.SceneNames[ASceneIndex] + KEY_SEP + IntToStr(AStringIndex);
end;

function TfrmMain.GetTranslation(ASceneIndex, AStringIndex: Integer): string;
begin
  if not FTrans.TryGetValue(TransKey(ASceneIndex, AStringIndex), Result) then
    Result := '';
end;

procedure TfrmMain.SetTranslation(ASceneIndex, AStringIndex: Integer;
  const AValue: string);
var
  K: string;
begin
  K := TransKey(ASceneIndex, AStringIndex);
  if AValue = '' then
    FTrans.Remove(K)
  else
    FTrans.AddOrSetValue(K, AValue);
end;

procedure TfrmMain.btnOpenPckClick(Sender: TObject);
var
  Dlg: TOpenDialog;
begin
  ApplyPendingEdit;
  if not AskSaveProject then
    Exit;
  Dlg := TOpenDialog.Create(Self);
  try
    Dlg.Title := 'Выберите Scene.pck';
    Dlg.Filter := 'SiglusEngine Scene.pck|Scene.pck|Все файлы|*.*';
    Dlg.Options := Dlg.Options + [ofFileMustExist];
    if not Dlg.Execute then
      Exit;
    Screen.Cursor := crHourGlass;
    try
      FPack.LoadFromFile(Dlg.FileName);
    finally
      Screen.Cursor := crDefault;
    end;
    FCurScene := -1;
    FOrig := nil;
    FRows := nil;
    lvStrings.Items.Count := 0;
    memoOrig.Clear;
    memoTrans.Clear;
    RefreshSceneList;
    UpdateStats;
    sbMain.SimpleText := Format('Загружено сцен: %d', [FPack.Count]);
  finally
    Dlg.Free;
  end;
end;

procedure TfrmMain.RefreshSceneList;
var
  I, N: Integer;
  Flt: string;
begin
  Flt := AnsiLowerCase(Trim(edtSceneFilter.Text));
  lstScenes.Items.BeginUpdate;
  try
    lstScenes.Clear;
    SetLength(FSceneMap, FPack.Count);
    N := 0;
    for I := 0 to FPack.Count - 1 do
      if (Flt = '') or (Pos(Flt, AnsiLowerCase(FPack.SceneNames[I])) > 0) then
      begin
        lstScenes.Items.Add(Format('%3d  %s', [I, FPack.SceneNames[I]]));
        FSceneMap[N] := I;
        Inc(N);
      end;
    SetLength(FSceneMap, N);
  finally
    lstScenes.Items.EndUpdate;
  end;
end;

procedure TfrmMain.edtSceneFilterChange(Sender: TObject);
begin
  if FPack.Count > 0 then
    RefreshSceneList;
end;

procedure TfrmMain.lstScenesClick(Sender: TObject);
var
  Idx: Integer;
begin
  ApplyPendingEdit;
  if (lstScenes.ItemIndex < 0) or (lstScenes.ItemIndex >= Length(FSceneMap)) then
    Exit;
  Idx := FSceneMap[lstScenes.ItemIndex];
  if Idx = FCurScene then
    Exit;
  Screen.Cursor := crHourGlass;
  try
    FCurScene := Idx;
    FOrig := FPack.GetSceneStrings(Idx);
  finally
    Screen.Cursor := crDefault;
  end;
  RefreshRows;
end;

procedure TfrmMain.RefreshRows;
var
  I, N: Integer;
  Flt: string;
  Keep: Boolean;
begin
  Flt := AnsiLowerCase(Trim(edtFilter.Text));
  SetLength(FRows, Length(FOrig));
  N := 0;
  for I := 0 to Length(FOrig) - 1 do
  begin
    Keep := True;
    if chkOnlyText.Checked and not LooksLikeText(FOrig[I]) then
      Keep := False;
    if Keep and chkOnlyUntranslated.Checked and
      (GetTranslation(FCurScene, I) <> '') then
      Keep := False;
    if Keep and (Flt <> '') then
      Keep := (Pos(Flt, AnsiLowerCase(FOrig[I])) > 0) or
        (Pos(Flt, AnsiLowerCase(GetTranslation(FCurScene, I))) > 0);
    if Keep then
    begin
      FRows[N] := I;
      Inc(N);
    end;
  end;
  SetLength(FRows, N);

  FCurRow := -1;
  memoOrig.Clear;
  memoTrans.Clear;
  lvStrings.Items.Count := N;
  lvStrings.Invalidate;
  lblRows.Caption := Format('Показано: %d из %d', [N, Length(FOrig)]);
  UpdateStats;
end;

procedure TfrmMain.edtFilterChange(Sender: TObject);
begin
  if FCurScene >= 0 then
    RefreshRows;
end;

procedure TfrmMain.lvStringsData(Sender: TObject; Item: TListItem);
var
  Idx: Integer;
begin
  if (Item.Index < 0) or (Item.Index >= Length(FRows)) then
    Exit;
  Idx := FRows[Item.Index];
  Item.Caption := IntToStr(Idx);
  Item.SubItems.Add(Flatten(FOrig[Idx]));
  Item.SubItems.Add(Flatten(GetTranslation(FCurScene, Idx)));
end;

procedure TfrmMain.lvStringsSelectItem(Sender: TObject; Item: TListItem;
  Selected: Boolean);
begin
  if not Selected then
    Exit;
  ApplyPendingEdit;
  ShowRow(Item.Index);
end;

procedure TfrmMain.ShowRow(ARow: Integer);
var
  Idx: Integer;
begin
  if (ARow < 0) or (ARow >= Length(FRows)) then
    Exit;
  FLoading := True;
  try
    FCurRow := ARow;
    Idx := FRows[ARow];
    memoOrig.Text := FOrig[Idx];
    memoTrans.Text := GetTranslation(FCurScene, Idx);
    gbOrig.Caption := Format('Оригинал  [строка %d]', [Idx]);
  finally
    FLoading := False;
  end;
end;

procedure TfrmMain.ApplyPendingEdit;
var
  Idx: Integer;
  NewVal: string;
begin
  if FLoading or (FCurScene < 0) or (FCurRow < 0) or (FCurRow >= Length(FRows)) then
    Exit;
  Idx := FRows[FCurRow];
  NewVal := memoTrans.Text;
  if NewVal = GetTranslation(FCurScene, Idx) then
    Exit;
  SetTranslation(FCurScene, Idx, NewVal);
  SetDirty(True);
  lvStrings.UpdateItems(FCurRow, FCurRow);
  UpdateStats;
end;

procedure TfrmMain.btnApplyClick(Sender: TObject);
begin
  ApplyPendingEdit;
end;

procedure TfrmMain.btnCopyOrigClick(Sender: TObject);
begin
  memoTrans.Text := memoOrig.Text;
  memoTrans.SetFocus;
end;

procedure TfrmMain.btnPrevClick(Sender: TObject);
begin
  ApplyPendingEdit;
  if FCurRow > 0 then
    lvStrings.ItemIndex := FCurRow - 1;
end;

procedure TfrmMain.btnNextClick(Sender: TObject);
begin
  ApplyPendingEdit;
  if FCurRow < Length(FRows) - 1 then
    lvStrings.ItemIndex := FCurRow + 1;
end;

procedure TfrmMain.memoTransKeyDown(Sender: TObject; var Key: Word;
  Shift: TShiftState);
begin
  if (Key = VK_RETURN) and (ssCtrl in Shift) then
  begin
    Key := 0;
    ApplyPendingEdit;
    btnNextClick(nil);
  end;
end;

procedure TfrmMain.UpdateStats;
var
  Done, I: Integer;
begin
  Done := 0;
  if FCurScene >= 0 then
    for I := 0 to Length(FOrig) - 1 do
      if GetTranslation(FCurScene, I) <> '' then
        Inc(Done);
  lblStats.Caption := Format('Сцен: %d    В сцене переведено: %d из %d    Всего строк в проекте: %d',
    [FPack.Count, Done, Length(FOrig), FTrans.Count]);
end;

procedure TfrmMain.btnSaveProjClick(Sender: TObject);
var
  Dlg: TSaveDialog;
  SL: TStringList;
  Pair: TPair<string, string>;
  P: Integer;
begin
  ApplyPendingEdit;
  if FProjFile = '' then
  begin
    Dlg := TSaveDialog.Create(Self);
    try
      Dlg.Title := 'Сохранить перевод';
      Dlg.Filter := 'Проект перевода (*.sptr)|*.sptr';
      Dlg.DefaultExt := 'sptr';
      if not Dlg.Execute then
        Exit;
      FProjFile := Dlg.FileName;
    finally
      Dlg.Free;
    end;
  end;

  SL := TStringList.Create;
  try
    SL.Add('# SPTranslate project v1');
    for Pair in FTrans do
    begin
      P := Pos(KEY_SEP, Pair.Key);
      SL.Add(Copy(Pair.Key, 1, P - 1) + #9 + Copy(Pair.Key, P + 1, MaxInt) +
        #9 + Escape(Pair.Value));
    end;
    SL.SaveToFile(FProjFile, TEncoding.UTF8);
  finally
    SL.Free;
  end;
  SetDirty(False);
  sbMain.SimpleText := Format('Сохранено записей: %d', [FTrans.Count]);
end;

procedure TfrmMain.btnLoadProjClick(Sender: TObject);
var
  Dlg: TOpenDialog;
  SL: TStringList;
  I, P1, P2: Integer;
  Line: string;
begin
  ApplyPendingEdit;
  if not AskSaveProject then
    Exit;
  Dlg := TOpenDialog.Create(Self);
  try
    Dlg.Title := 'Загрузить перевод';
    Dlg.Filter := 'Проект перевода (*.sptr)|*.sptr|Все файлы|*.*';
    Dlg.Options := Dlg.Options + [ofFileMustExist];
    if not Dlg.Execute then
      Exit;
    FProjFile := Dlg.FileName;
  finally
    Dlg.Free;
  end;

  SL := TStringList.Create;
  try
    SL.LoadFromFile(FProjFile, TEncoding.UTF8);
    FTrans.Clear;
    for I := 0 to SL.Count - 1 do
    begin
      Line := SL[I];
      if (Line = '') or (Line[1] = '#') then
        Continue;
      P1 := Pos(#9, Line);
      if P1 = 0 then
        Continue;
      P2 := PosEx(#9, Line, P1 + 1);
      if P2 = 0 then
        Continue;
      FTrans.AddOrSetValue(
        Copy(Line, 1, P1 - 1) + KEY_SEP + Copy(Line, P1 + 1, P2 - P1 - 1),
        Unescape(Copy(Line, P2 + 1, MaxInt)));
    end;
  finally
    SL.Free;
  end;
  SetDirty(False);
  if FCurScene >= 0 then
    RefreshRows;
  UpdateStats;
  sbMain.SimpleText := Format('Загружено записей: %d', [FTrans.Count]);
end;

procedure TfrmMain.PackProgress(Sender: TObject; Current, Total: Integer);
begin
  if (Current mod 10 = 0) or (Current = Total) then
  begin
    sbMain.SimpleText := Format('Сборка: %d / %d', [Current, Total]);
    Application.ProcessMessages;
  end;
end;

procedure TfrmMain.PackGetStrings(Sender: TObject; SceneIndex: Integer;
  var Strings: TStringArray);
var
  I: Integer;
  T: string;
begin
  for I := 0 to Length(Strings) - 1 do
    if FTrans.TryGetValue(TransKey(SceneIndex, I), T) and (T <> '') then
      Strings[I] := T;
end;

procedure TfrmMain.btnBuildClick(Sender: TObject);
var
  Dlg: TSaveDialog;
begin
  ApplyPendingEdit;
  if FPack.Count = 0 then
  begin
    ShowMessage('Сначала откройте Scene.pck');
    Exit;
  end;
  Dlg := TSaveDialog.Create(Self);
  try
    Dlg.Title := 'Сохранить собранный Scene.pck';
    Dlg.Filter := 'Scene.pck|*.pck';
    Dlg.DefaultExt := 'pck';
    Dlg.FileName := 'Scene.pck';
    if not Dlg.Execute then
      Exit;
    Screen.Cursor := crHourGlass;
    btnBuild.Enabled := False;
    try
      FPack.BuildToFile(Dlg.FileName);
      sbMain.SimpleText := 'Готово: ' + Dlg.FileName;
      ShowMessage('Scene.pck собран.'#13#10 +
        'Не забудьте сделать резервную копию оригинала.');
    finally
      btnBuild.Enabled := True;
      Screen.Cursor := crDefault;
    end;
  finally
    Dlg.Free;
  end;
end;

end.
