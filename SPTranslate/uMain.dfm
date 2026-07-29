object frmMain: TfrmMain
  Left = 0
  Top = 0
  Caption = 'SP RB Translator'
  ClientHeight = 800
  ClientWidth = 1300
  Color = clBtnFace
  Font.Charset = DEFAULT_CHARSET
  Font.Color = clWindowText
  Font.Height = -12
  Font.Name = 'Segoe UI'
  Font.Style = []
  Position = poScreenCenter
  OnCloseQuery = FormCloseQuery
  OnCreate = FormCreate
  OnDestroy = FormDestroy
  TextHeight = 15
  object pnlTop: TPanel
    Left = 0
    Top = 0
    Width = 1300
    Height = 48
    Align = alTop
    BevelOuter = bvNone
    TabOrder = 0
    object lblStats: TLabel
      Left = 776
      Top = 17
      Width = 40
      Height = 15
      Caption = '-'
    end
    object btnOpenPck: TButton
      Left = 8
      Top = 9
      Width = 170
      Height = 30
      Caption = #1054#1090#1082#1088#1099#1090#1100' Scene.pck...'
      TabOrder = 0
      OnClick = btnOpenPckClick
    end
    object btnLoadProj: TButton
      Left = 186
      Top = 9
      Width = 180
      Height = 30
      Caption = #1047#1072#1075#1088#1091#1079#1080#1090#1100' '#1087#1077#1088#1077#1074#1086#1076'...'
      TabOrder = 1
      OnClick = btnLoadProjClick
    end
    object btnSaveProj: TButton
      Left = 374
      Top = 9
      Width = 180
      Height = 30
      Caption = #1057#1086#1093#1088#1072#1085#1080#1090#1100' '#1087#1077#1088#1077#1074#1086#1076
      TabOrder = 2
      OnClick = btnSaveProjClick
    end
    object btnBuild: TButton
      Left = 562
      Top = 9
      Width = 190
      Height = 30
      Caption = #1057#1086#1073#1088#1072#1090#1100' Scene.pck...'
      TabOrder = 3
      OnClick = btnBuildClick
    end
  end
  object sbMain: TStatusBar
    Left = 0
    Top = 781
    Width = 1300
    Height = 19
    Panels = <>
    SimplePanel = True
  end
  object pnlLeft: TPanel
    Left = 0
    Top = 48
    Width = 290
    Height = 733
    Align = alLeft
    BevelOuter = bvNone
    TabOrder = 2
    object pnlSceneFilter: TPanel
      Left = 0
      Top = 0
      Width = 290
      Height = 30
      Align = alTop
      BevelOuter = bvNone
      TabOrder = 0
      object edtSceneFilter: TEdit
        Left = 0
        Top = 0
        Width = 290
        Height = 23
        Align = alTop
        TabOrder = 0
        TextHint = #1092#1080#1083#1100#1090#1088' '#1089#1094#1077#1085
        OnChange = edtSceneFilterChange
      end
    end
    object lstScenes: TListBox
      Left = 0
      Top = 30
      Width = 290
      Height = 703
      Align = alClient
      ItemHeight = 15
      TabOrder = 1
      OnClick = lstScenesClick
    end
  end
  object splLeft: TSplitter
    Left = 290
    Top = 48
    Width = 5
    Height = 733
  end
  object pnlMain: TPanel
    Left = 295
    Top = 48
    Width = 1005
    Height = 733
    Align = alClient
    BevelOuter = bvNone
    TabOrder = 3
    object pnlFilter: TPanel
      Left = 0
      Top = 0
      Width = 1005
      Height = 34
      Align = alTop
      BevelOuter = bvNone
      TabOrder = 0
      object lblRows: TLabel
        Left = 672
        Top = 10
        Width = 8
        Height = 15
        Caption = '-'
      end
      object edtFilter: TEdit
        Left = 6
        Top = 5
        Width = 320
        Height = 23
        TabOrder = 0
        TextHint = #1087#1086#1080#1089#1082' '#1087#1086' '#1090#1077#1082#1089#1090#1091
        OnChange = edtFilterChange
      end
      object chkOnlyText: TCheckBox
        Left = 340
        Top = 8
        Width = 120
        Height = 17
        Caption = #1058#1086#1083#1100#1082#1086' '#1076#1080#1072#1083#1086#1075#1080
        Checked = True
        State = cbChecked
        TabOrder = 1
        OnClick = edtFilterChange
      end
      object chkOnlyUntranslated: TCheckBox
        Left = 474
        Top = 8
        Width = 180
        Height = 17
        Caption = #1058#1086#1083#1100#1082#1086' '#1085#1077#1087#1077#1088#1077#1074#1077#1076#1105#1085#1085#1099#1077
        TabOrder = 2
        OnClick = edtFilterChange
      end
    end
    object pnlEdit: TPanel
      Left = 0
      Top = 493
      Width = 1005
      Height = 240
      Align = alBottom
      BevelOuter = bvNone
      TabOrder = 1
      object splEdit: TSplitter
        Left = 620
        Top = 0
        Width = 5
        Height = 198
      end
      object pnlEditButtons: TPanel
        Left = 0
        Top = 198
        Width = 1005
        Height = 42
        Align = alBottom
        BevelOuter = bvNone
        TabOrder = 0
        object lblHint: TLabel
          Left = 642
          Top = 14
          Width = 300
          Height = 15
          Caption = 'Ctrl+Enter '#8212' '#1087#1088#1080#1084#1077#1085#1080#1090#1100' '#1080' '#1087#1077#1088#1077#1081#1090#1080' '#1082' '#1089#1083#1077#1076#1091#1102#1097#1077#1081' '#1089#1090#1088#1086#1082#1077
        end
        object btnApply: TButton
          Left = 6
          Top = 6
          Width = 180
          Height = 30
          Caption = #1055#1088#1080#1084#1077#1085#1080#1090#1100
          TabOrder = 0
          OnClick = btnApplyClick
        end
        object btnCopyOrig: TButton
          Left = 194
          Top = 6
          Width = 190
          Height = 30
          Caption = #1057#1082#1086#1087#1080#1088#1086#1074#1072#1090#1100' '#1086#1088#1080#1075#1080#1085#1072#1083
          TabOrder = 1
          OnClick = btnCopyOrigClick
        end
        object btnPrev: TButton
          Left = 392
          Top = 6
          Width = 110
          Height = 30
          Caption = #1053#1072#1079#1072#1076
          TabOrder = 2
          OnClick = btnPrevClick
        end
        object btnNext: TButton
          Left = 510
          Top = 6
          Width = 110
          Height = 30
          Caption = #1042#1087#1077#1088#1105#1076
          TabOrder = 3
          OnClick = btnNextClick
        end
      end
      object gbOrig: TGroupBox
        Left = 0
        Top = 0
        Width = 620
        Height = 198
        Align = alLeft
        Caption = #1054#1088#1080#1075#1080#1085#1072#1083
        TabOrder = 1
        object memoOrig: TMemo
          Left = 2
          Top = 17
          Width = 616
          Height = 179
          Align = alClient
          Color = clBtnFace
          ReadOnly = True
          ScrollBars = ssVertical
          TabOrder = 0
        end
      end
      object gbTrans: TGroupBox
        Left = 625
        Top = 0
        Width = 380
        Height = 198
        Align = alClient
        Caption = #1055#1077#1088#1077#1074#1086#1076
        TabOrder = 2
        object memoTrans: TMemo
          Left = 2
          Top = 17
          Width = 376
          Height = 179
          Align = alClient
          ScrollBars = ssVertical
          TabOrder = 0
          OnKeyDown = memoTransKeyDown
        end
      end
    end
    object splMain: TSplitter
      Left = 0
      Top = 488
      Width = 1005
      Height = 5
      Cursor = crVSplit
      Align = alBottom
    end
    object lvStrings: TListView
      Left = 0
      Top = 34
      Width = 1005
      Height = 454
      Align = alClient
      Columns = <
        item
          Caption = #8470
          Width = 60
        end
        item
          Caption = #1054#1088#1080#1075#1080#1085#1072#1083
          Width = 460
        end
        item
          Caption = #1055#1077#1088#1077#1074#1086#1076
          Width = 460
        end>
      GridLines = True
      HideSelection = False
      OwnerData = True
      ReadOnly = True
      RowSelect = True
      TabOrder = 2
      ViewStyle = vsReport
      OnData = lvStringsData
      OnSelectItem = lvStringsSelectItem
    end
  end
end
