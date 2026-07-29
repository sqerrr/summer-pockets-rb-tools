{ ============================================================================
  uSiglus - reading and rebuilding SiglusEngine Scene.pck
  Target: Summer Pockets REFLECTION BLUE (SiglusEngine 1.1.134)

  Format (reverse engineered from SiglusEngine.exe):
    Scene.pck header: 0x5C bytes = 1 dword (size) + 10 pairs (offset, count)
      pair  7 -> scene name index      (offset, count), names follow inline
      pair  9 -> scene data index      (offset, size) per scene
      pair 10 -> scene data blobs
    Scene blob: XOR with 256-byte key (index mod 256), then LZSS:
      dword compressed size (whole blob), dword raw size, then
      flag byte (LSB first): bit=1 -> literal, bit=0 -> word
      offset = w shr 4, count = (w and $F) + 2, copied byte by byte.
    Scene header: 132 bytes = 1 dword (size) + 16 pairs (offset, count)
      pair 2 -> string index (charOffset, charLength) per entry
      pair 3 -> string data, UTF-16LE
    Each string is XORed per 16-bit unit with (stringIndex * $7087) and $FFFF.
  ============================================================================ }
unit uSiglus;

interface

uses
  System.SysUtils, System.Classes;

type
  ESiglusError = class(Exception);

  TStringArray = TArray<string>;

  TSceneInfo = record
    Name: string;
    Offset: Cardinal;
    Size: Cardinal;
  end;

  TProgressEvent = procedure(Sender: TObject; Current, Total: Integer) of object;
  TGetStringsEvent = procedure(Sender: TObject; SceneIndex: Integer;
    var Strings: TStringArray) of object;

  TScenePack = class
  private
    FData: TBytes;
    FScenes: TArray<TSceneInfo>;
    FDataOffset: Cardinal;
    FIndexOffset: Cardinal;
    FOnProgress: TProgressEvent;
    FOnGetStrings: TGetStringsEvent;
    function GetCount: Integer;
    function GetSceneName(Index: Integer): string;
  public
    procedure LoadFromFile(const AFileName: string);
    { Decrypted and decompressed scene body. }
    function GetSceneData(Index: Integer): TBytes;
    { Decoded string pool of a scene. }
    function GetSceneStrings(Index: Integer): TStringArray;
    { Rebuilds the whole pack, asking OnGetStrings for replacement strings. }
    procedure BuildToFile(const AFileName: string);
    property Count: Integer read GetCount;
    property SceneNames[Index: Integer]: string read GetSceneName;
    property OnProgress: TProgressEvent read FOnProgress write FOnProgress;
    property OnGetStrings: TGetStringsEvent read FOnGetStrings write FOnGetStrings;
  end;

function SiglusXor(const Src: TBytes): TBytes;
function LzDecompress(const Src: TBytes): TBytes;
function LzCompressLiteral(const Src: TBytes): TBytes;
function SceneReadStrings(const Scene: TBytes): TStringArray;
function SceneWriteStrings(const Scene: TBytes; const NewStrings: TStringArray): TBytes;

{ The engine gives a character a full-width cell exactly when it encodes to two
  bytes in Shift-JIS, and Cyrillic sits in JIS X 0208 rows 6-7. Font metrics are
  ignored entirely. Russian is therefore carried by Latin Extended-A codepoints
  (U+0100..U+0141), none of which exist in Shift-JIS, so they stay half-width.
  The font maps those carriers to the Cyrillic outlines. }
function EncodeRussian(const S: string): string;
function DecodeRussian(const S: string): string;

implementation

const
  STR_KEY_MUL = $7087;

  { 256-byte XOR key, taken from SiglusEngine.exe .rdata at VA 0x00ADABB0 }
  SIGLUS_KEY: array [0 .. 255] of Byte = (
    $70, $F8, $A6, $B0, $A1, $A5, $28, $4F, $B5, $2F, $48, $FA, $E1, $E9, $4B, $DE,
    $B7, $4F, $62, $95, $8B, $E0, $03, $80, $E7, $CF, $0F, $6B, $92, $01, $EB, $F8,
    $A2, $88, $CE, $63, $04, $38, $D2, $6D, $8C, $D2, $88, $76, $A7, $92, $71, $8F,
    $4E, $B6, $8D, $01, $79, $88, $83, $0A, $F9, $E9, $2C, $DB, $67, $DB, $91, $14,
    $D5, $9A, $4E, $79, $17, $23, $08, $96, $0E, $1D, $15, $F9, $A5, $A0, $6F, $58,
    $17, $C8, $A9, $46, $DA, $22, $FF, $FD, $87, $12, $42, $FB, $A9, $B8, $67, $6C,
    $91, $67, $64, $F9, $D1, $1E, $E4, $50, $64, $6F, $F2, $0B, $DE, $40, $E7, $47,
    $F1, $03, $CC, $2A, $AD, $7F, $34, $21, $A0, $64, $26, $98, $6C, $ED, $69, $F4,
    $B5, $23, $08, $6E, $7D, $92, $F6, $EB, $93, $F0, $7A, $89, $5E, $F9, $F8, $7A,
    $AF, $E8, $A9, $48, $C2, $AC, $11, $6B, $2B, $33, $A7, $40, $0D, $DC, $7D, $A7,
    $5B, $CF, $C8, $31, $D1, $77, $52, $8D, $82, $AC, $41, $B8, $73, $A5, $4F, $26,
    $7C, $0F, $39, $DA, $5B, $37, $4A, $DE, $A4, $49, $0B, $7C, $17, $A3, $43, $AE,
    $77, $06, $64, $73, $C0, $43, $A3, $18, $5A, $0F, $9F, $02, $4C, $7E, $8B, $01,
    $9F, $2D, $AE, $72, $54, $13, $FF, $96, $AE, $0B, $34, $58, $CF, $E3, $00, $78,
    $BE, $E3, $F5, $61, $E4, $87, $7C, $FC, $80, $AF, $C4, $8D, $46, $3A, $5D, $D0,
    $36, $BC, $E5, $60, $77, $68, $08, $4F, $BB, $AB, $E2, $78, $07, $E8, $73, $BF);

  { Scene header dword indexes }
  SH_STR_INDEX_OFF = 3;
  SH_STR_COUNT     = 4;
  SH_STR_DATA_OFF  = 5;

  { Pack header dword indexes }
  PH_NAME_INDEX_OFF = 13;
  PH_SCENE_COUNT    = 14;
  PH_DATA_INDEX_OFF = 17;
  PH_DATA_OFF       = 19;

{ XOR is symmetric, so the same routine encrypts and decrypts. }
function SiglusXor(const Src: TBytes): TBytes;
var
  I, N: Integer;
begin
  N := Length(Src);
  SetLength(Result, N);
  for I := 0 to N - 1 do
    Result[I] := Src[I] xor SIGLUS_KEY[I and $FF];
end;

function LzDecompress(const Src: TBytes): TBytes;
var
  RawSize, SrcLen: Integer;
  Sp, Dp, Off, Cnt, K, Bit: Integer;
  Flag: Byte;
  W: Word;
begin
  SrcLen := Length(Src);
  if SrcLen < 8 then
    raise ESiglusError.Create('Compressed block is too small');
  RawSize := Integer(PCardinal(@Src[4])^);
  SetLength(Result, RawSize);
  Sp := 8;
  Dp := 0;
  while Dp < RawSize do
  begin
    if Sp >= SrcLen then
      raise ESiglusError.Create('Unexpected end of compressed data');
    Flag := Src[Sp];
    Inc(Sp);
    for Bit := 0 to 7 do
    begin
      if Dp >= RawSize then
        Break;
      if (Flag and 1) <> 0 then
      begin
        Result[Dp] := Src[Sp];
        Inc(Sp);
        Inc(Dp);
      end
      else
      begin
        W := Word(Src[Sp]) or (Word(Src[Sp + 1]) shl 8);
        Inc(Sp, 2);
        Off := W shr 4;
        Cnt := (W and $F) + 2;
        if (Off = 0) or (Off > Dp) then
          raise ESiglusError.CreateFmt('Bad back reference: offset %d at %d', [Off, Dp]);
        { Blocks may overlap, so this must stay a byte by byte copy. }
        for K := 1 to Cnt do
        begin
          if Dp >= RawSize then
            Break;
          Result[Dp] := Result[Dp - Off];
          Inc(Dp);
        end;
      end;
      Flag := Flag shr 1;
    end;
  end;
end;

{ Produces a valid stream without any back references. It is ~12.5% larger
  than the original but the engine accepts it, which keeps repacking trivial. }
function LzCompressLiteral(const Src: TBytes): TBytes;
var
  N, I, J, Dp: Integer;
begin
  N := Length(Src);
  SetLength(Result, 8 + N + (N + 7) div 8);
  I := 0;
  Dp := 8;
  while I < N do
  begin
    Result[Dp] := $FF;
    Inc(Dp);
    for J := 1 to 8 do
    begin
      if I >= N then
        Break;
      Result[Dp] := Src[I];
      Inc(Dp);
      Inc(I);
    end;
  end;
  SetLength(Result, Dp);
  PCardinal(@Result[0])^ := Cardinal(Dp);
  PCardinal(@Result[4])^ := Cardinal(N);
end;

function SceneReadStrings(const Scene: TBytes): TStringArray;
var
  IdxOff, Cnt, DatOff, CharOff, CharLen: Cardinal;
  I, J, N: Integer;
  Key: Word;
  P: PWord;
  S: string;
begin
  if Length(Scene) < 132 then
    raise ESiglusError.Create('Scene body is too small');
  IdxOff := PCardinal(@Scene[SH_STR_INDEX_OFF * 4])^;
  Cnt := PCardinal(@Scene[SH_STR_COUNT * 4])^;
  DatOff := PCardinal(@Scene[SH_STR_DATA_OFF * 4])^;
  SetLength(Result, Cnt);
  for I := 0 to Integer(Cnt) - 1 do
  begin
    CharOff := PCardinal(@Scene[IdxOff + Cardinal(I) * 8])^;
    CharLen := PCardinal(@Scene[IdxOff + Cardinal(I) * 8 + 4])^;
    N := Integer(CharLen);
    SetLength(S, N);
    if N > 0 then
    begin
      Key := Word((I * STR_KEY_MUL) and $FFFF);
      P := PWord(@Scene[DatOff + CharOff * 2]);
      for J := 1 to N do
      begin
        S[J] := WideChar(P^ xor Key);
        Inc(P);
      end;
    end;
    Result[I] := S;
  end;
end;

function SceneWriteStrings(const Scene: TBytes; const NewStrings: TStringArray): TBytes;
var
  IdxOff, Cnt, DatOff, LastOff, LastLen: Cardinal;
  I, J, N, TotalChars, OldEnd, TailLen, DstIdx, DstDat, CharPos: Integer;
  Key: Word;
  P: PWord;
  S: string;
begin
  IdxOff := PCardinal(@Scene[SH_STR_INDEX_OFF * 4])^;
  Cnt := PCardinal(@Scene[SH_STR_COUNT * 4])^;
  DatOff := PCardinal(@Scene[SH_STR_DATA_OFF * 4])^;

  if Cardinal(Length(NewStrings)) <> Cnt then
    raise ESiglusError.CreateFmt(
      'String count mismatch: got %d, scene expects %d', [Length(NewStrings), Cnt]);
  if DatOff <> IdxOff + Cnt * 8 then
    raise ESiglusError.Create('Unexpected scene layout: index is not followed by data');

  { Everything after the string pool (a 2-byte terminator) is preserved as is. }
  if Cnt > 0 then
  begin
    LastOff := PCardinal(@Scene[IdxOff + (Cnt - 1) * 8])^;
    LastLen := PCardinal(@Scene[IdxOff + (Cnt - 1) * 8 + 4])^;
    OldEnd := Integer(DatOff + (LastOff + LastLen) * 2);
  end
  else
    OldEnd := Integer(DatOff);
  TailLen := Length(Scene) - OldEnd;
  if TailLen < 0 then
    raise ESiglusError.Create('String pool runs past the end of the scene');

  TotalChars := 0;
  for I := 0 to Length(NewStrings) - 1 do
    Inc(TotalChars, Length(NewStrings[I]));

  DstIdx := Integer(IdxOff);
  DstDat := DstIdx + Integer(Cnt) * 8;
  SetLength(Result, DstDat + TotalChars * 2 + TailLen);
  Move(Scene[0], Result[0], IdxOff);

  CharPos := 0;
  for I := 0 to Integer(Cnt) - 1 do
  begin
    S := NewStrings[I];
    N := Length(S);
    PCardinal(@Result[DstIdx + I * 8])^ := Cardinal(CharPos);
    PCardinal(@Result[DstIdx + I * 8 + 4])^ := Cardinal(N);
    if N > 0 then
    begin
      Key := Word((I * STR_KEY_MUL) and $FFFF);
      P := PWord(@Result[DstDat + CharPos * 2]);
      for J := 1 to N do
      begin
        P^ := Word(S[J]) xor Key;
        Inc(P);
      end;
    end;
    Inc(CharPos, N);
  end;

  if TailLen > 0 then
    Move(Scene[OldEnd], Result[DstDat + TotalChars * 2], TailLen);
end;

const
  CARRIER_BASE = $0100;   { U+0100..U+011F  А..Я without Ё }
  CARRIER_YO_U = $0120;   { U+0120          Ё }
  CARRIER_LOW = $0121;    { U+0121..U+0140  а..я without ё }
  CARRIER_YO_L = $0141;   { U+0141          ё }

function EncodeRussian(const S: string): string;
var
  I: Integer;
  C: Word;
begin
  SetLength(Result, Length(S));
  for I := 1 to Length(S) do
  begin
    C := Word(S[I]);
    case C of
      $0410 .. $042F: Result[I] := WideChar(CARRIER_BASE + (C - $0410));
      $0401:          Result[I] := WideChar(CARRIER_YO_U);
      $0430 .. $044F: Result[I] := WideChar(CARRIER_LOW + (C - $0430));
      $0451:          Result[I] := WideChar(CARRIER_YO_L);
      { em/en dash have no glyph in these fonts; U+2015 does and looks right }
      $2013, $2014:   Result[I] := WideChar($2015);
    else
      Result[I] := S[I];
    end;
  end;
end;

function DecodeRussian(const S: string): string;
var
  I: Integer;
  C: Word;
begin
  SetLength(Result, Length(S));
  for I := 1 to Length(S) do
  begin
    C := Word(S[I]);
    case C of
      CARRIER_BASE .. CARRIER_BASE + 31: Result[I] := WideChar($0410 + (C - CARRIER_BASE));
      CARRIER_YO_U:                      Result[I] := WideChar($0401);
      CARRIER_LOW .. CARRIER_LOW + 31:   Result[I] := WideChar($0430 + (C - CARRIER_LOW));
      CARRIER_YO_L:                      Result[I] := WideChar($0451);
    else
      Result[I] := S[I];
    end;
  end;
end;

{ TScenePack }

function TScenePack.GetCount: Integer;
begin
  Result := Length(FScenes);
end;

function TScenePack.GetSceneName(Index: Integer): string;
begin
  Result := FScenes[Index].Name;
end;

procedure TScenePack.LoadFromFile(const AFileName: string);
var
  FS: TFileStream;
  NameIdxOff, SceneCount, NameDatOff, CharOff, CharLen: Cardinal;
  I: Integer;
  S: string;
begin
  FS := TFileStream.Create(AFileName, fmOpenRead or fmShareDenyWrite);
  try
    SetLength(FData, FS.Size);
    FS.ReadBuffer(FData[0], FS.Size);
  finally
    FS.Free;
  end;

  if (Length(FData) < $5C) or (PCardinal(@FData[0])^ <> $5C) then
    raise ESiglusError.Create('This is not a SiglusEngine Scene.pck file');

  NameIdxOff := PCardinal(@FData[PH_NAME_INDEX_OFF * 4])^;
  SceneCount := PCardinal(@FData[PH_SCENE_COUNT * 4])^;
  FIndexOffset := PCardinal(@FData[PH_DATA_INDEX_OFF * 4])^;
  FDataOffset := PCardinal(@FData[PH_DATA_OFF * 4])^;
  NameDatOff := NameIdxOff + SceneCount * 8;

  SetLength(FScenes, SceneCount);
  for I := 0 to Integer(SceneCount) - 1 do
  begin
    CharOff := PCardinal(@FData[NameIdxOff + Cardinal(I) * 8])^;
    CharLen := PCardinal(@FData[NameIdxOff + Cardinal(I) * 8 + 4])^;
    SetLength(S, CharLen);
    if CharLen > 0 then
      Move(FData[NameDatOff + CharOff * 2], S[1], CharLen * 2);
    FScenes[I].Name := S;
    FScenes[I].Offset := PCardinal(@FData[FIndexOffset + Cardinal(I) * 8])^;
    FScenes[I].Size := PCardinal(@FData[FIndexOffset + Cardinal(I) * 8 + 4])^;
  end;
end;

function TScenePack.GetSceneData(Index: Integer): TBytes;
var
  Blob: TBytes;
begin
  SetLength(Blob, FScenes[Index].Size);
  Move(FData[FDataOffset + FScenes[Index].Offset], Blob[0], FScenes[Index].Size);
  Result := LzDecompress(SiglusXor(Blob));
end;

function TScenePack.GetSceneStrings(Index: Integer): TStringArray;
begin
  Result := SceneReadStrings(GetSceneData(Index));
end;

procedure TScenePack.BuildToFile(const AFileName: string);
var
  MS: TMemoryStream;
  I: Integer;
  Scene, Blob: TBytes;
  Strs: TStringArray;
  Offsets, Sizes: TArray<Cardinal>;
  Cur: Cardinal;
begin
  MS := TMemoryStream.Create;
  try
    MS.WriteBuffer(FData[0], FDataOffset);
    SetLength(Offsets, Count);
    SetLength(Sizes, Count);
    Cur := 0;
    for I := 0 to Count - 1 do
    begin
      Scene := GetSceneData(I);
      { Strs comes in filled with the originals; the handler only replaces
        the entries it has a translation for. }
      Strs := SceneReadStrings(Scene);
      if Assigned(FOnGetStrings) then
        FOnGetStrings(Self, I, Strs);
      Scene := SceneWriteStrings(Scene, Strs);
      Blob := SiglusXor(LzCompressLiteral(Scene));
      Offsets[I] := Cur;
      Sizes[I] := Cardinal(Length(Blob));
      MS.WriteBuffer(Blob[0], Length(Blob));
      Inc(Cur, Cardinal(Length(Blob)));
      if Assigned(FOnProgress) then
        FOnProgress(Self, I + 1, Count);
    end;

    MS.Position := FIndexOffset;
    for I := 0 to Count - 1 do
    begin
      MS.WriteBuffer(Offsets[I], 4);
      MS.WriteBuffer(Sizes[I], 4);
    end;

    MS.SaveToFile(AFileName);
  finally
    MS.Free;
  end;
end;

end.
