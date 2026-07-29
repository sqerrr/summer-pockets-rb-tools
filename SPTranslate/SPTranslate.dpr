program SPTranslate;

uses
  Vcl.Forms,
  uMain in 'uMain.pas' {frmMain},
  uSiglus in 'uSiglus.pas';

{$R *.res}

begin
  Application.Initialize;
  Application.MainFormOnTaskbar := True;
  Application.Title := 'SP RB Translator';
  Application.CreateForm(TfrmMain, frmMain);
  Application.Run;
end.
