"""Styling for the main tab containers."""

from src.gui.styles.table_styles import SCROLLBAR_STYLE


TAB_STYLE = """
    QWidget#TabRoot {
        background-color: #EEF3F6;
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    }

    /* ---------- Page header ---------- */
    QFrame#PageHeader {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        border-radius: 14px;
        border: none;
    }
    QLabel#PageTitle {
        color: #FFFFFF;
        font-size: 22px;
        font-weight: 700;
        letter-spacing: 0.4px;
        background: transparent;
    }
    QLabel#PageSubtitle {
        color: rgba(255, 255, 255, 0.88);
        font-size: 12px;
        background: transparent;
    }
    QLabel#PageBadge {
        color: #0B3B3B;
        background-color: rgba(255, 255, 255, 0.85);
        border-radius: 12px;
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 600;
    }

    /* ---------- Toolbar ---------- */
    QFrame#Toolbar {
        background-color: #FFFFFF;
        border: 1px solid #D8E2E8;
        border-radius: 12px;
    }
    QLineEdit#SearchInput {
        background-color: #F4F7F9;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 22px;
        font-size: 12px;
        color: #1F2A33;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
    }
    QLineEdit#SearchInput:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QLineEdit#SearchInput:focus {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }

    /* ---------- Buttons ---------- */
    QPushButton#PrimaryButton {
        min-width: 170px;
        padding: 10px 20px;
        border-radius: 10px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.4px;
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        border: 1px solid #3FA3A3;
    }
    QPushButton#PrimaryButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #62CACA, stop:1 #46B0B0);
    }
    QPushButton#PrimaryButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3FA3A3, stop:1 #2F8B8B);
    }
    QPushButton#PrimaryButton:disabled {
        background: #BCD3D3;
        border-color: #BCD3D3;
        color: #EAF4F4;
    }

    QPushButton#DangerButton {
        min-width: 170px;
        padding: 10px 20px;
        border-radius: 10px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.4px;
        color: #B23A48;
        background-color: #FFFFFF;
        border: 1px solid #E7C2C7;
    }
    QPushButton#DangerButton:hover {
        background-color: #FBEDEF;
        border-color: #D98A95;
        color: #8E2A37;
    }
    QPushButton#DangerButton:pressed {
        background-color: #F4DADE;
    }
    QPushButton#DangerButton:disabled {
        color: #C9B2B5;
        border-color: #ECDDDF;
        background-color: #FAF5F6;
    }

    /* ---------- Footer status strip ---------- */
    QLabel#StatusLabel {
        color: #6B7A85;
        font-size: 11px;
        padding: 2px 4px;
    }
""" + SCROLLBAR_STYLE

