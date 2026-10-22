# -*- coding: utf-8 -*-

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


APP_FONT_FAMILY = "Microsoft YaHei UI"
APP_FONT_FALLBACK = "Microsoft YaHei"
APP_FONT_SIZE = 10

MONO_FONT_FAMILY = "Consolas"
MONO_FONT_SIZE = 10


def get_app_font(
    size: int = APP_FONT_SIZE,
    bold: bool = False,
) -> QFont:
    """
    返回现代 Windows 界面字体。

    优先：
    1. Microsoft YaHei UI
    2. Microsoft YaHei
    3. Segoe UI
    """

    available_families = set(
        QFontDatabase.families()
    )

    preferred_fonts = [
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Segoe UI",
    ]

    family = None

    for font_name in preferred_fonts:
        if font_name in available_families:
            family = font_name
            break

    if family is None:
        family = QApplication.font().family()

    font = QFont(
        family,
        size,
    )

    font.setBold(
        bold
    )

    return font


def get_mono_font(size: int = MONO_FONT_SIZE) -> QFont:
    return QFont(
        MONO_FONT_FAMILY,
        size,
    )


def apply_global_font(app: QApplication) -> None:
    app.setFont(
        get_app_font()
    )


def get_dark_theme() -> str:
    """
    BAIXIONG Studio
    Black Gold Edition
    """

    return """

    /* =========================================================
       GLOBAL
       ========================================================= */

    QMainWindow {
        background-color: #090A0C;
        color: #F2F2F2;
    }

    QWidget {
        color: #E8E8E8;
        font-size: 15px;
    }

    /*
       非常重要：
       QLabel 默认透明。
       解决文字后面出现深色矩形块的问题。
    */

    QLabel {
        background-color: transparent;
        border: none;
        color: #E8E8E8;
    }

    QCheckBox {
        background-color: transparent;
    }

    QRadioButton {
        background-color: transparent;
    }

    QToolTip {
        background-color: #171717;
        color: #F5D77A;
        border: 1px solid #8A6A22;
        padding: 6px;
    }


    /* =========================================================
       MENU BAR
       ========================================================= */

    QMenuBar {
        background-color: #0D0E11;
        color: #EAEAEA;

        border: none;
        border-bottom: 1px solid #29231A;

        padding: 4px 8px;
    }

    QMenuBar::item {
        background-color: transparent;

        padding: 7px 14px;

        margin: 1px 2px;

        border-radius: 6px;
    }

    QMenuBar::item:selected {
        background-color: #221C10;
        color: #E9C765;
    }

    QMenuBar::item:pressed {
        background-color: #2B2312;
        color: #F4D878;
    }


    QMenu {
        background-color: #121316;

        color: #E8E8E8;

        border: 1px solid #3A3020;

        padding: 7px;
    }

    QMenu::item {
        padding: 8px 28px 8px 12px;

        border-radius: 5px;

        background-color: transparent;
    }

    QMenu::item:selected {
        background-color: #282010;
        color: #F1D06B;
    }

    QMenu::separator {
        height: 1px;

        background-color: #3A3020;

        margin: 6px 5px;
    }


    /* =========================================================
       TOOL BAR
       ========================================================= */

    QToolBar {
        background-color: #101114;

        border: none;
        border-bottom: 1px solid #29231A;

        spacing: 6px;

        padding: 5px 8px;
    }

    QToolBar::separator {
        background-color: #3A3020;

        width: 1px;

        margin: 5px 7px;
    }

    QToolButton {
        background-color: transparent;

        color: #D9D9D9;

        border: 1px solid transparent;

        border-radius: 7px;

        padding: 7px 11px;
    }

    QToolButton:hover {
        background-color: #211B10;

        color: #F1D06B;

        border-color: #4A3A1A;
    }

    QToolButton:pressed {
        background-color: #302714;

        color: #FFE59A;
    }


    /* =========================================================
       SIDEBAR
       ========================================================= */

    QWidget#Sidebar {
        background-color: #0E0F12;

        border-right: 1px solid #2E281C;
    }

    QLabel#BrandTitle {
        background-color: transparent;

        color: #EBCB70;

        font-size: 22px;

        font-weight: bold;
    }

    QLabel#BrandSubtitle {
        background-color: transparent;

        color: #8E8E8E;

        font-size: 12px;
    }


    QPushButton#NavButton {
        background-color: transparent;

        color: #AAA7A0;

        border: 1px solid transparent;

        border-radius: 8px;

        padding-left: 16px;
        padding-right: 12px;

        text-align: left;

        font-size: 15px;
    }

    QPushButton#NavButton:hover {
        background-color: #171610;

        color: #E5C866;

        border: 1px solid #292315;
    }

    QPushButton#NavButton:checked {
        background-color: #211C10;

        color: #F0D374;

        border: 1px solid #4D3D18;

        border-left: 3px solid #D2A93C;

        padding-left: 13px;

        font-weight: bold;
    }


    /* =========================================================
       TOP BAR
       ========================================================= */

    QFrame#TopBar {
        background-color: #111216;

        border: 1px solid #32291A;

        border-radius: 12px;
    }

    QLabel#TopTitle {
        background-color: transparent;

        color: #E7C45D;

        font-size: 22px;

        font-weight: bold;
    }

    QLabel#TopSubtitle {
        background-color: transparent;

        color: #858585;

        font-size: 13px;
    }


    QLabel#StatusBadge {
        background-color: #17150F;

        color: #CBB46B;

        border: 1px solid #3A311D;

        border-radius: 7px;

        padding: 5px 9px;

        font-size: 12px;
    }

    /* =========================================================
       HEADER SAVE STATUS
       ========================================================= */

    QFrame#HeaderStatusBox {
        background-color: #0D0E11;

        border: 1px solid #30291D;

        border-radius: 8px;
    }


    QFrame#HeaderStatusBox:hover {
        border-color: #4B3B1A;
    }


    QLabel#HeaderStatusTitle {
        background-color: transparent;

        color: #777777;

        font-size: 11px;
    }


    QLabel#HeaderStatusValue {
        background-color: transparent;

        color: #E5E5E5;

        font-size: 13px;

        font-weight: bold;
    }


    QLabel#HeaderStatusValue[state="success"] {
        color: #D7B851;
    }


    QLabel#HeaderStatusValue[state="idle"] {
        color: #777777;
    }


    /* =========================================================
       PAGE TITLES
       ========================================================= */

    QLabel#PageTitle {
        background-color: transparent;

        color: #F1D06B;

        font-size: 25px;

        font-weight: bold;
    }


    QLabel#PageSubtitle {
        background-color: transparent;

        color: #9B9B9B;

        font-size: 14px;
    }


    /* =========================================================
       CARDS
       ========================================================= */

    QFrame#Card {
        background-color: #121317;

        border: 1px solid #2D281D;

        border-radius: 11px;
    }


    QFrame#Card:hover {
        border: 1px solid #46391B;
    }


    QLabel#CardTitle {
        background-color: transparent;

        color: #EAC963;

        font-size: 17px;

        font-weight: bold;
    }


    QLabel#CardDescription {
        background-color: transparent;

        color: #A7A7A7;

        font-size: 13px;

        border: none;
    }


    /* =========================================================
       GROUP BOX
       ========================================================= */

    QGroupBox {
        background-color: #121317;

        border: 1px solid #30291D;

        border-radius: 10px;

        margin-top: 15px;

        padding-top: 12px;
    }

    QGroupBox::title {
        subcontrol-origin: margin;

        subcontrol-position: top left;

        left: 12px;

        padding: 0 7px;

        background-color: transparent;

        color: #E7C35A;

        font-weight: bold;
    }


    /* =========================================================
       BUTTONS
       ========================================================= */

    QPushButton {
        background-color: #1A1B1F;

        color: #E6E6E6;

        border: 1px solid #423821;

        border-radius: 8px;

        padding: 9px 16px;

        min-height: 22px;
    }


    QPushButton:hover {
        background-color: #242116;

        color: #F3D675;

        border-color: #806525;
    }


    QPushButton:pressed {
        background-color: #181610;

        border-color: #A5832D;
    }


    QPushButton:disabled {
        background-color: #151619;

        color: #555555;

        border-color: #262626;
    }


    QPushButton#PrimaryButton {
        background-color: #B28B2C;

        color: #101010;

        border: 1px solid #D1AB48;

        font-weight: bold;
    }


    QPushButton#PrimaryButton:hover {
        background-color: #C69D35;

        color: #080808;

        border-color: #E0BE62;
    }


    QPushButton#PrimaryButton:pressed {
        background-color: #967420;
    }


    QPushButton#DangerButton {
        background-color: #382024;

        color: #F0CCCC;

        border: 1px solid #6D353D;
    }


    QPushButton#DangerButton:hover {
        background-color: #4B282E;

        border-color: #8C454F;
    }


    /* =========================================================
       INPUTS
       ========================================================= */

    QLineEdit,
    QSpinBox,
    QComboBox {
        background-color: #0C0D10;

        color: #F1F1F1;

        border: 1px solid #3A3428;

        border-radius: 7px;

        padding: 7px 9px;

        selection-background-color: #A8812B;

        selection-color: #080808;
    }


    QLineEdit:focus,
    QSpinBox:focus,
    QComboBox:focus {
        border: 1px solid #C29A36;
    }


    QComboBox::drop-down {
        border: none;

        width: 28px;
    }


    QComboBox QAbstractItemView {
        background-color: #111216;

        color: #ECECEC;

        border: 1px solid #45391E;

        selection-background-color: #2A2314;

        selection-color: #F3D675;
    }


    /* =========================================================
       CHECKBOX
       ========================================================= */

    QCheckBox {
        color: #D8D8D8;

        spacing: 8px;
    }


    QCheckBox::indicator {
        width: 17px;

        height: 17px;
    }


    QCheckBox::indicator:unchecked {
        background-color: #0D0E10;

        border: 1px solid #4A4234;

        border-radius: 4px;
    }


    QCheckBox::indicator:checked {
        background-color: #C39931;

        border: 1px solid #E3BB57;

        border-radius: 4px;
    }


    /* =========================================================
       JSON + LOG
       ========================================================= */

    QPlainTextEdit {
        background-color: #090A0C;

        color: #DDDDDD;

        border: 1px solid #30291D;

        border-radius: 9px;

        padding: 8px;

        selection-background-color: #725A21;

        selection-color: #FFFFFF;
    }


    QPlainTextEdit#JsonEditor {
        background-color: #08090B;

        color: #D8D8D8;

        border: 1px solid #3A3020;
    }


    QPlainTextEdit#LogBox {
        background-color: #0B0C0E;

        color: #BEB49A;

        border: 1px solid #30291D;
    }


    /* =========================================================
       SCROLL AREA
       ========================================================= */

    QScrollArea {
        background-color: transparent;

        border: none;
    }

    QScrollArea > QWidget > QWidget {
        background-color: transparent;
    }


    /* =========================================================
       SCROLL BARS
       ========================================================= */

    QScrollBar:vertical {
        background-color: transparent;

        width: 10px;

        margin: 2px;
    }


    QScrollBar::handle:vertical {
        background-color: #3A3428;

        min-height: 30px;

        border-radius: 5px;
    }


    QScrollBar::handle:vertical:hover {
        background-color: #655226;
    }


    QScrollBar::add-line:vertical,
    QScrollBar::sub-line:vertical {
        height: 0;
    }


    QScrollBar:horizontal {
        background-color: transparent;

        height: 10px;

        margin: 2px;
    }


    QScrollBar::handle:horizontal {
        background-color: #3A3428;

        min-width: 30px;

        border-radius: 5px;
    }


    QScrollBar::handle:horizontal:hover {
        background-color: #655226;
    }


    QScrollBar::add-line:horizontal,
    QScrollBar::sub-line:horizontal {
        width: 0;
    }


    /* =========================================================
       STATUS BAR
       ========================================================= */

    QStatusBar {
        background-color: #0E0F12;

        color: #9F967B;

        border-top: 1px solid #29231A;
    }

    """


def apply_dark_theme(app: QApplication) -> None:
    apply_global_font(app)

    app.setStyleSheet(
        get_dark_theme()
    )