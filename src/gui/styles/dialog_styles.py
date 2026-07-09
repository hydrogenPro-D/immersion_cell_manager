"""Dialog styling - matches the modern table aesthetic."""

from src.gui.styles.table_styles import SCROLLBAR_STYLE


DIALOG_STYLE = """
    QDialog {
        background-color: #F4F7F9;
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    }

    /* Decorative header banner */
    QFrame#DialogHeader {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
        border: none;
    }
    QLabel#DialogTitle {
        color: #FFFFFF;
        font-size: 18px;
        font-weight: 600;
        letter-spacing: 0.4px;
        padding: 0px;
        background: transparent;
    }
    QLabel#DialogSubtitle {
        color: rgba(255, 255, 255, 0.85);
        font-size: 12px;
        background: transparent;
    }

    /* Card body */
    QFrame#DialogBody {
        background-color: #FFFFFF;
        border-bottom-left-radius: 12px;
        border-bottom-right-radius: 12px;
        border: 1px solid #D8E2E8;
        border-top: none;
    }

    /* Field labels */
    QLabel#FieldLabel {
        color: #4A5A66;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.6px;
        background: transparent;
        padding-top: 4px;
        padding-bottom: 6px;
    }

    /* Inputs */
    QLineEdit {
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 9px 12px;
        min-height: 22px;
        font-size: 13px;
        color: #1F2A33;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
    }
    QLineEdit:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QLineEdit:focus {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }
    QLineEdit:disabled {
        color: #9AA7B0;
        background-color: #ECEFF2;
    }
    QLineEdit[readOnly="true"] {
        background-color: #EEF3F6;
        color: #4A5A66;
        border: 1px dashed #C7D3DB;
    }
    QLineEdit[readOnly="true"]:hover,
    QLineEdit[readOnly="true"]:focus {
        background-color: #EEF3F6;
        border: 1px dashed #C7D3DB;
    }

    /* --------- Choice (QComboBox) --------- */
    QComboBox#ChoiceField {
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 22px;
        font-size: 13px;
        color: #1F2A33;
    }
    QComboBox#ChoiceField:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QComboBox#ChoiceField:focus,
    QComboBox#ChoiceField:on {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }
    QComboBox#ChoiceField:disabled {
        color: #9AA7B0;
        background-color: #ECEFF2;
    }
    QComboBox#ChoiceField::drop-down {
        border: none;
        width: 0px;
        subcontrol-origin: padding;
        subcontrol-position: top right;
    }
    QComboBox#ChoiceField::down-arrow {
        image: none;
        width: 0px;
        height: 0px;
        border: none;
    }
    QComboBox#ChoiceField QAbstractItemView {
        background-color: #FFFFFF;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 4px;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
        outline: 0;
    }
    QComboBox#ChoiceField QAbstractItemView::item {
        padding: 7px 10px;
        border-radius: 6px;
    }

    /* --------- Project (QComboBox with visible dropdown arrow) --------- */
    QComboBox#ProjectField {
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 8px 12px;
        padding-right: 34px;
        min-height: 22px;
        font-size: 13px;
        color: #1F2A33;
    }
    QComboBox#ProjectField:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QComboBox#ProjectField:focus,
    QComboBox#ProjectField:on {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }
    QComboBox#ProjectField::drop-down {
        border: none;
        width: 0px;
        subcontrol-origin: padding;
        subcontrol-position: top right;
    }
    QComboBox#ProjectField::down-arrow {
        image: none;
        width: 0px;
        height: 0px;
        border: none;
    }
    QComboBox#ProjectField QAbstractItemView {
        background-color: #FFFFFF;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 4px;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
        outline: 0;
    }
    QComboBox#ProjectField QAbstractItemView::item {
        padding: 7px 10px;
        border-radius: 6px;
    }

    /* --------- Date (QDateEdit) --------- */
    QDateEdit#DateField {
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 22px;
        font-size: 13px;
        color: #1F2A33;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
    }
    QDateEdit#DateField:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QDateEdit#DateField:focus {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }
    QDateEdit#DateField[readOnly="true"] {
        background-color: #EEF3F6;
        color: #4A5A66;
        border: 1px dashed #C7D3DB;
    }
    QDateEdit#DateField::drop-down {
        border: none;
        width: 34px;
        subcontrol-origin: padding;
        subcontrol-position: top right;
    }
    QDateEdit#DateField::down-arrow {
        image: none;
        width: 0px;
        height: 0px;
        border: none;
    }
    QCalendarWidget QToolButton {
        color: #1F2A33;
        background-color: transparent;
        padding: 6px;
        border-radius: 6px;
    }
    QCalendarWidget QToolButton:hover {
        background-color: #E6F4F4;
    }
    QCalendarWidget QWidget#qt_calendar_navigationbar {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
    }
    /* Year editor on the navigation bar. Without an explicit rule the year
       number renders invisibly (white/clipped) while editing, so the user
       can't see the year they're changing. Give it a solid white field with
       dark text and enough width for four digits. */
    QCalendarWidget QSpinBox {
        background-color: #FFFFFF;
        color: #1F2A33;
        border: 1px solid #D8E2E8;
        border-radius: 6px;
        min-width: 64px;
        padding: 2px 6px;
        margin: 4px 2px;
        font-size: 13px;
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
    }
    QCalendarWidget QSpinBox::up-button {
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 16px;
    }
    QCalendarWidget QSpinBox::down-button {
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 16px;
    }
    QCalendarWidget QAbstractItemView:enabled {
        selection-background-color: #BFE6E6;
        selection-color: #0B3B3B;
        color: #1F2A33;
        background-color: #FFFFFF;
    }

    /* --------- Hours SpinBox --------- */
    QSpinBox#HoursSpinBox {
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
        border-radius: 8px;
        padding: 8px 12px;
        min-height: 22px;
        font-size: 13px;
        color: #1F2A33;
    }
    QSpinBox#HoursSpinBox:hover {
        border: 1px solid #BBD0D8;
        background-color: #FFFFFF;
    }
    QSpinBox#HoursSpinBox:focus {
        border: 1px solid #3FA3A3;
        background-color: #FFFFFF;
    }
    QSpinBox#HoursSpinBox:disabled {
        color: #9AA7B0;
        background-color: #ECEFF2;
    }
    QSpinBox#HoursSpinBox::up-button,
    QSpinBox#HoursSpinBox::down-button {
        width: 20px;
        background-color: #F7FAFC;
        border: 1px solid #D8E2E8;
    }
    QSpinBox#HoursSpinBox::up-button:hover,
    QSpinBox#HoursSpinBox::down-button:hover {
        background-color: #E6F4F4;
    }
    QSpinBox#HoursSpinBox::up-arrow,
    QSpinBox#HoursSpinBox::down-arrow {
        width: 8px;
        height: 8px;
    }

    QScrollArea {
        background: transparent;
        border: none;
    }
    QScrollArea > QWidget > QWidget {
        background: transparent;
    }

    /* Buttons */
    QDialogButtonBox {
        background: transparent;
    }
    QPushButton {
        min-width: 96px;
        padding: 9px 18px;
        border-radius: 8px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.4px;
        border: 1px solid #D8E2E8;
        background-color: #FFFFFF;
        color: #4A5A66;
    }
    QPushButton:hover {
        background-color: #F0F4F6;
        border-color: #BBD0D8;
        color: #1F2A33;
    }
    QPushButton:pressed {
        background-color: #E2EAEF;
    }
    QPushButton:default {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        color: #FFFFFF;
        border: 1px solid #3FA3A3;
    }
    QPushButton:default:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #62CACA, stop:1 #46B0B0);
    }
    QPushButton:default:pressed {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3FA3A3, stop:1 #2F8B8B);
    }
""" + SCROLLBAR_STYLE


