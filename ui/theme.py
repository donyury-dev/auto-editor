"""Tema visual do Auto Editor (Fase 7): escuro, estilo CapCut.

QSS puro (sem framework novo): leve, não aumenta o tamanho do pacote.
"""

from __future__ import annotations

DARK_QSS = """
QWidget {
    background-color: #1e1e24;
    color: #e8e8ec;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #17171c;
}
QLabel#appTitle {
    font-size: 19px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#appSubtitle {
    color: #8b8b96;
    font-size: 12px;
}
QLabel#sectionTitle {
    font-size: 15px;
    font-weight: 600;
    color: #ffffff;
}
QPushButton {
    background-color: #2a2a33;
    color: #e8e8ec;
    border: 1px solid #3a3a46;
    border-radius: 6px;
    padding: 7px 14px;
}
QPushButton:hover {
    background-color: #34343f;
    border-color: #4a4a58;
}
QPushButton:pressed {
    background-color: #26262e;
}
QPushButton:disabled {
    color: #666670;
    background-color: #232329;
    border-color: #2e2e38;
}
QPushButton#accent {
    background-color: #0bb5a6;
    color: #06110f;
    font-weight: 700;
    border: none;
    font-size: 14px;
    padding: 11px 18px;
}
QPushButton#accent:hover {
    background-color: #12c9b9;
}
QPushButton#accent:disabled {
    background-color: #1e4a45;
    color: #0a3f39;
}
QPushButton#navButton {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
    color: #b9b9c4;
}
QPushButton#navButton:hover {
    background-color: #26262e;
    color: #ffffff;
}
QPushButton#navButton:checked {
    background-color: #2c2c36;
    color: #0fe0cc;
    font-weight: 600;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #26262e;
    border: 1px solid #3a3a46;
    border-radius: 6px;
    padding: 6px 8px;
    color: #e8e8ec;
}
QLineEdit:focus, QComboBox:focus {
    border-color: #0bb5a6;
}
QComboBox QAbstractItemView {
    background-color: #26262e;
    color: #e8e8ec;
    selection-background-color: #0bb5a6;
    selection-color: #06110f;
}
QPlainTextEdit, QTextEdit {
    background-color: #1a1a20;
    border: 1px solid #2e2e38;
    border-radius: 6px;
    color: #c8c8d2;
    font-family: Consolas, monospace;
    font-size: 12px;
}
QProgressBar {
    background-color: #26262e;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #0bb5a6;
    border-radius: 5px;
}
QTableWidget {
    background-color: #1e1e24;
    alternate-background-color: #232329;
    gridline-color: #2e2e38;
    border: 1px solid #2e2e38;
    border-radius: 6px;
}
QHeaderView::section {
    background-color: #26262e;
    color: #b9b9c4;
    border: none;
    padding: 6px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #2e2e38;
    border-radius: 6px;
    background-color: #1e1e24;
}
QTabBar::tab {
    background-color: transparent;
    color: #8b8b96;
    padding: 8px 16px;
}
QTabBar::tab:selected {
    color: #0fe0cc;
    border-bottom: 2px solid #0bb5a6;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #4a4a58;
    border-radius: 4px;
    background: #26262e;
}
QCheckBox::indicator:checked {
    background: #0bb5a6;
    border-color: #0bb5a6;
}
QMenuBar {
    background-color: #17171c;
    color: #b9b9c4;
}
QMenuBar::item:selected {
    background-color: #26262e;
}
QMenu {
    background-color: #26262e;
    color: #e8e8ec;
    border: 1px solid #3a3a46;
}
QMenu::item:selected {
    background-color: #0bb5a6;
    color: #06110f;
}
QScrollBar:vertical {
    background: #1a1a20;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #3a3a46;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
}
QLabel#statusOk { color: #34d1c0; }
QLabel#statusErr { color: #ff6b6b; }
"""
