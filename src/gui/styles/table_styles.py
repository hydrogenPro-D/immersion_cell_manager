"""Table styling for PyQt elements - Modern design."""

# Pixel sizes for scrollbars. Keep these in sync with the values used inside
# SCROLLBAR_STYLE below, other modules (e.g. activator_gui) import these to
# size sibling widgets so the layout stays aligned if these values change.
SCROLLBAR_VERTICAL_WIDTH = 25
SCROLLBAR_HORIZONTAL_HEIGHT = 25

# Shared scrollbar styling for all widgets
SCROLLBAR_STYLE = f"""
    QScrollBar:vertical {{
        border: none;
        background-color: #F0F0F0;
        width: {SCROLLBAR_VERTICAL_WIDTH}px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background-color: #C0C0C0;
        border-radius: 12px;
        min-height: 20px;
        margin: 2px 2px 2px 2px;
        border: none;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: #A0A0A0;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        border: none;
        background: none;
    }}
    QScrollBar:horizontal {{
        border: none;
        background-color: #F0F0F0;
        height: {SCROLLBAR_HORIZONTAL_HEIGHT}px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: #C0C0C0;
        border-radius: 12px;
        min-width: 20px;
        margin: 2px 2px 2px 2px;
        border: none;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: #A0A0A0;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        border: none;
        background: none;
    }}
"""

TABLE_STYLE = """
    QTableWidget {
        background-color: #FFFFFF;
        alternate-background-color: #F7FAFC;
        gridline-color: transparent;
        border: 1px solid #D8E2E8;
        border-radius: 12px;
        margin: 12px 0px;
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
        font-size: 12px;
        color: #1F2A33;
        selection-background-color: transparent;
        selection-color: #0B3B3B;
        outline: 0;
    }
    QTableWidget::item {
        padding: 2px 14px;
        border: none;
        border-bottom: 1px solid #ECEFF2;
        color: #1F2A33;
    }
    QTableWidget::item:alternate {
        background-color: #F7FAFC;
    }
    QTableWidget::item:selected {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #BFE6E6, stop:1 #9ED6D6);
        color: #0B3B3B;
        border: none;
    }
    QTableCornerButton::section {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        border: none;
        border-top-left-radius: 12px;
    }
    QHeaderView {
        background-color: transparent;
        border: none;
    }
    QHeaderView::section {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #55BDBD, stop:1 #3FA3A3);
        color: #FFFFFF;
        padding: 12px 14px;
        border: none;
        border-right: 1px solid rgba(255, 255, 255, 0.18);
        font-weight: 600;
        font-size: 12px;
        font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
        letter-spacing: 0.4px;
    }
    QHeaderView::section:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #62CACA, stop:1 #46B0B0);
    }
    QHeaderView::section:first {
        border-top-left-radius: 12px;
    }
    QHeaderView::section:last {
        border-right: none;
        border-top-right-radius: 12px;
    }
    QHeaderView::section:vertical {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #EEF3F6, stop:1 #E2EAEF);
        color: #4A5A66;
        border-bottom: 1px solid #D8E2E8;
        font-weight: 600;
    }
""" + SCROLLBAR_STYLE

