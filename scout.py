#!/usr/bin/env python3
"""WaveScout Main Application Window"""

import sys
import time
import argparse
import os
import subprocess
import platform
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
from PySide6.QtWidgets import (QApplication, QMainWindow, 
                              QSplitter, QTreeView, QFileDialog, QDialog,
                              QMessageBox, QProgressDialog, QAbstractItemView,
                              QToolBar, QStyle, QStyleFactory, QWidget, QHBoxLayout,
                              QVBoxLayout, QPushButton, QLabel, QFrame, QMenuBar,
                              QSizeGrip, QMenu, QStatusBar, QSizePolicy)
from qframelesswindow import FramelessWindow
from wavescout.message_box_utils import show_critical, show_warning, show_information, show_question
from PySide6.QtCore import Qt, QThreadPool, QRunnable, Signal, QObject, QSettings, QEvent, QPoint, QSize
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPainter, QColor, QPen, QIcon, QPixmap
from wavescout import WaveScoutWidget, create_sample_session, save_session, load_session
from wavescout.design_tree_view import DesignTreeView
from wavescout.config import RENDERING
from wavescout.theme import theme_manager, ThemeName, apply_saved_theme
from wavescout.data_model import WaveformSession, TreeNode, GroupNode
from wavescout.settings_manager import SettingsManager
from wavescout.timing_utils import set_startup_time, tprint
import qdarkstyle


class LoaderSignals(QObject):
    """Signals for loader runnable."""
    finished = Signal(object)
    error = Signal(str)


class LoaderRunnable(QRunnable):
    """Runnable for loading files in thread pool."""
    
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = LoaderSignals()
        
    def run(self):
        """Execute the loading function."""
        try:
            result = self.func(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            self.signals.error.emit(error_msg)




@dataclass
class LoadingState:
    """Manages all loading-related temporary state."""
    session_path: Optional[Path] = None
    temp_reload_path: Optional[Path] = None
    pending_session: Optional[WaveformSession] = None
    pending_loaded_session: Optional[WaveformSession] = None
    pending_signal_nodes: List[TreeNode] = field(default_factory=list)
    cli_snippets: List[str] = field(default_factory=list)
    
    def clear(self) -> None:
        """Clear all loading state."""
        if self.temp_reload_path and self.temp_reload_path.exists():
            try:
                self.temp_reload_path.unlink()
            except:
                pass
        # Reset to defaults
        self.session_path = None
        self.temp_reload_path = None
        self.pending_session = None
        self.pending_loaded_session = None
        self.pending_signal_nodes = []
        self.cli_snippets = []


class WaveScoutMainWindow(FramelessWindow):
    """Main window for WaveScout App."""
    
    def __init__(self, session_file=None, wave_file: str | None = None, exit_after_load: bool = False):
        init_start = time.time()
        tprint(f"  WaveScoutMainWindow.__init__ starting...")
        super().__init__()
        self.setWindowTitle("WaveScout - Waveform Viewer")
        self.resize(1400, 800)
        
        # Initialize thread pool and progress dialog
        self.thread_pool = QThreadPool()
        self.progress_dialog = None

        # Initialize settings manager
        self.settings_manager = SettingsManager()
        # Keep backward compatibility reference to QSettings
        self.settings = self.settings_manager.get_settings()
        
        # Store current UI scale
        self.current_ui_scale = self.settings_manager.get_ui_scale()
        
        # Apply saved theme
        apply_saved_theme(self.settings)
        
        # Connect theme change signal for automatic repainting
        theme_manager.themeChanged.connect(self._on_theme_changed)
        tprint(f"  Theme connections set")
        
        # Connect to system theme changes if available
        from PySide6.QtWidgets import QStyleFactory
        app = QApplication.instance()
        if app and hasattr(app, 'paletteChanged'):
            app.paletteChanged.connect(self._on_system_palette_changed)
        
        # Store current waveform file for reload
        self.current_wave_file: str | None = None
        
        
        # Initialize loading state management
        self._loading_state = LoadingState()
        self.signal_loading_dialog: Optional[QProgressDialog] = None
        
        # Initialize optional components
        self.design_tree_view: Optional[DesignTreeView] = None
        
        # Create status bar early for compatibility
        self._status_bar = QStatusBar()
        
        # Setup title bar with menu and panel toggle buttons
        tprint(f"  Setting up title bar...")
        self._setup_title_bar()

        # Apply FramelessWindow theme styling after components are created
        tprint(f"  Applying frameless styling...")
        self._apply_frameless_styling()
        
        # Create main container widget that fills the window below title bar
        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.container.setGeometry(0, self.titleBar.height(), self.width(), 
                                   self.height() - self.titleBar.height())
        
        # Apply container styling after it's created
        self._apply_container_styling()
        
        # Main vertical layout for container content
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create vertical splitter for main area and bottom panel
        self.vertical_splitter = QSplitter(Qt.Vertical)
        self.vertical_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3E3E42;
                height: 1px;
            }
            QSplitter::handle:hover {
                background-color: #007ACC;
            }
        """)
        
        # Create horizontal splitter for left/center/right
        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        self.horizontal_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #3E3E42;
                width: 1px;
            }
            QSplitter::handle:hover {
                background-color: #007ACC;
            }
        """)
        
        # Add horizontal splitter to vertical splitter
        self.vertical_splitter.addWidget(self.horizontal_splitter)
        
        # Create design tree view (left panel)
        self.left_panel = self.design_tree_view = DesignTreeView()
        self.design_tree_view.signals_selected.connect(self._on_signals_selected)
        self.design_tree_view.status_message.connect(self.statusBar().showMessage)
        self.design_tree_view.install_event_filters()
        
        # Add design tree view to horizontal splitter first (left)
        self.horizontal_splitter.addWidget(self.left_panel)
        
        # Create wave view widget (center panel)
        tprint(f"  Creating WaveScoutWidget...")
        self.wave_widget = WaveScoutWidget()
        self.horizontal_splitter.addWidget(self.wave_widget)
        
        # Create right sidebar with snippet browser
        from wavescout.snippet_browser_widget import SnippetBrowserWidget
        self.right_panel = SnippetBrowserWidget()
        self.right_panel.snippet_instantiate.connect(self._on_snippet_instantiate)
        self.horizontal_splitter.addWidget(self.right_panel)
        
        # Create bottom panel (placeholder for now)
        self.bottom_panel = QFrame()
        self.bottom_panel.setFrameShape(QFrame.NoFrame)
        self.bottom_panel.setStyleSheet("background-color: #252526;")
        self.bottom_panel_layout = QVBoxLayout(self.bottom_panel)
        self.bottom_panel_layout.setContentsMargins(8, 8, 8, 8)
        self.bottom_panel_layout.addWidget(QLabel("Bottom Panel Content", styleSheet="color: #CCCCCC"))
        self.vertical_splitter.addWidget(self.bottom_panel)
        
        # Add vertical splitter to main layout (below toolbar that will be added)
        self.main_layout.addWidget(self.vertical_splitter)
        
        # Add status bar at the bottom
        self.main_layout.addWidget(self._status_bar)
        
        # Load value tooltip preference
        value_tooltips_enabled = self.settings_manager.get_value_tooltips_enabled()
        self.wave_widget.set_value_tooltips_enabled(value_tooltips_enabled)
        
        # Load highlight selected preference
        highlight_selected_enabled = self.settings_manager.get_highlight_selected()
        self.wave_widget.set_highlight_selected(highlight_selected_enabled)
        
        # Connect navigation signal from signal names view to design tree view
        # The signal now emits (scope_path, signal_name)
        self.wave_widget._names_view.navigate_to_scope_requested.connect(
            lambda scope, signal: self.design_tree_view.navigate_to_scope(scope, signal)
        )
        
        # Set default splitter sizes first, then restore panel states
        self.horizontal_splitter.setSizes([420, 730, 250])
        self.vertical_splitter.setSizes([600, 200])
        
        # Set stretch factors for horizontal splitter
        # Only the center widget (WaveScoutWidget) should expand horizontally
        self.horizontal_splitter.setStretchFactor(0, 0)  # Design tree - fixed width
        self.horizontal_splitter.setStretchFactor(1, 1)  # Wave widget - takes all extra space
        self.horizontal_splitter.setStretchFactor(2, 0)  # Snippets panel - fixed width
        
        # Set stretch factors for vertical splitter
        # Only the main area should expand vertically
        self.vertical_splitter.setStretchFactor(0, 1)  # Main area - takes all extra space
        self.vertical_splitter.setStretchFactor(1, 0)  # Bottom panel - fixed height
        
        # Restore panel states from settings after setting initial sizes
        self._restore_panel_states()
        
        # Create actions first (shared between menu and toolbar)
        self._create_actions()
        
        # Create menus using the menu bar in title bar
        self._create_menus()
        
        # Create toolbar after actions are created
        self._create_toolbar()
        
        # Connect panel toggle buttons (after title bar setup)
        self._connect_panel_toggles()
        
        # Initialize status bar
        self.statusBar().showMessage("Ready")
        
        # Schedule initial load after event loop starts
        from PySide6.QtCore import QTimer

        # Store exit-after-load flag
        self.exit_after_load = exit_after_load

        if session_file:
            # Load the provided session file
            QTimer.singleShot(100, lambda: self.load_session_file(session_file))
        elif wave_file:
            # Handle wave_file with optional snippets
            if isinstance(wave_file, list):
                actual_wave_file = wave_file[0]
                self._loading_state.cli_snippets = wave_file[1:]
            else:
                actual_wave_file = wave_file
                self._loading_state.cli_snippets = []
            # Load the provided waveform file (vcd/fst)
            QTimer.singleShot(100, lambda: self.load_file(actual_wave_file))
        else:
            # No file specified, start with empty application
            # Ensure waveform-related actions are disabled until a file is loaded
            self._set_waveform_actions_enabled(False)

        tprint(f"  WaveScoutMainWindow.__init__ completed in {time.time() - init_start:.3f}s")
        
    def _setup_title_bar(self):
        """Setup the title bar with menu bar and panel toggle buttons."""
        # Create menu bar as child of title bar
        self.menu_bar = QMenuBar(self.titleBar)
        self.menu_bar.setNativeMenuBar(False)  # Ensure it's embedded in the window
        
        # Insert menu bar into title bar layout at the beginning (position 0)
        self.titleBar.layout().insertWidget(0, self.menu_bar, 0, Qt.AlignLeft)
        
        # Add stretch to push panel buttons to the right (position 1)
        self.titleBar.layout().insertStretch(1, 1)
        
        # Create panel toggle buttons container
        buttons_container = QWidget()
        buttons_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)  # Don't expand
        buttons_layout = QHBoxLayout(buttons_container)
        buttons_layout.setContentsMargins(0, 0, 12, 0)  # Margin to separate from window controls
        buttons_layout.setSpacing(1)  # Tighter spacing for professional look
        
        # Toggle left sidebar button
        self.left_button = QPushButton()
        self.left_button.setCheckable(True)
        self.left_button.setChecked(True)
        self.left_button.setIcon(self._create_sidebar_icon(Qt.LeftArrow))
        self.left_button.setFixedSize(28, 28)  # Slightly smaller for better proportions
        self.left_button.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); border-radius: 4px; } "
            "QPushButton:checked { background-color: rgba(0, 120, 212, 0.3); border-radius: 4px; }")
        self.left_button.setToolTip("Toggle Left Panel")
        buttons_layout.addWidget(self.left_button)
        
        # Toggle right sidebar button
        self.right_button = QPushButton()
        self.right_button.setCheckable(True)
        self.right_button.setChecked(True)
        self.right_button.setIcon(self._create_sidebar_icon(Qt.RightArrow))
        self.right_button.setFixedSize(28, 28)
        self.right_button.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); border-radius: 4px; } "
            "QPushButton:checked { background-color: rgba(0, 120, 212, 0.3); border-radius: 4px; }")
        self.right_button.setToolTip("Toggle Right Panel")
        buttons_layout.addWidget(self.right_button)
        
        # Toggle bottom panel button
        self.bottom_button = QPushButton()
        self.bottom_button.setCheckable(True)
        self.bottom_button.setChecked(True)
        self.bottom_button.setIcon(self._create_bottom_panel_icon())
        self.bottom_button.setFixedSize(28, 28)
        self.bottom_button.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; } "
            "QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); border-radius: 4px; } "
            "QPushButton:checked { background-color: rgba(0, 120, 212, 0.3); border-radius: 4px; }")
        self.bottom_button.setToolTip("Toggle Bottom Panel")
        buttons_layout.addWidget(self.bottom_button)
        
        # Insert the buttons container just before the minimize button if available,
        # otherwise fall back to placing it before the last item (window controls group).
        layout = self.titleBar.layout()
        insert_index = max(layout.count() - 1, 0)
        try:
            # Some qframelesswindow title bars expose minBtn directly; if so, prefer its index
            if hasattr(self.titleBar, 'minBtn') and self.titleBar.minBtn is not None:
                idx = layout.indexOf(self.titleBar.minBtn)
                if idx != -1:
                    insert_index = idx  # place immediately before minBtn
        except Exception:
            # If any unexpected structure, keep fallback index
            pass
        layout.insertWidget(insert_index, buttons_container, 0, Qt.AlignVCenter)
        
        # Ensure title bar is raised
        self.titleBar.raise_()
    
    def statusBar(self) -> QStatusBar:
        """Return the status bar (compatibility method)."""
        return self._status_bar
    
    def _apply_frameless_styling(self):
        """Apply theme-aware styling to FramelessWindow components."""
        # Detect if system is using dark theme
        is_dark = self._is_system_dark_theme()
        
        if is_dark:
            # Dark theme styling
            menu_style = """
                QMenuBar {
                    background-color: transparent;
                    color: white;
                    border: none;
                    padding: 2px;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 6px 8px;
                    border-radius: 4px;
                }
                QMenuBar::item:selected {
                    background-color: #505050;
                }
                QMenuBar::item:pressed {
                    background-color: #606060;
                }
                QMenu {
                    background-color: #252526;
                    color: #CCCCCC;
                    border: 1px solid #3E3E42;
                    border-radius: 6px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 20px;
                    border-radius: 4px;
                }
                QMenu::item:selected {
                    background-color: #007ACC;
                }
                QMenu::separator {
                    height: 1px;
                    background-color: #3E3E42;
                    margin: 4px 10px;
                }
            """
            # Update panel toggle buttons for dark theme
            button_style = """
                QPushButton { 
                    background-color: transparent; 
                    border: none; 
                    color: white;
                } 
                QPushButton:hover { 
                    background-color: #505050; 
                    border-radius: 4px; 
                } 
                QPushButton:checked { 
                    background-color: #007ACC; 
                    border-radius: 4px; 
                }
            """
        else:
            # Light theme styling
            menu_style = """
                QMenuBar {
                    background-color: transparent;
                    color: palette(window-text);
                    border: none;
                    padding: 2px;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 6px 8px;
                    border-radius: 4px;
                }
                QMenuBar::item:selected {
                    background-color: rgba(0, 0, 0, 0.1);
                }
                QMenuBar::item:pressed {
                    background-color: rgba(0, 0, 0, 0.2);
                }
                QMenu {
                    background-color: palette(base);
                    color: palette(text);
                    border: 1px solid palette(mid);
                    border-radius: 6px;
                    padding: 4px;
                }
                QMenu::item {
                    padding: 6px 20px;
                    border-radius: 4px;
                }
                QMenu::item:selected {
                    background-color: palette(highlight);
                    color: palette(highlighted-text);
                }
                QMenu::separator {
                    height: 1px;
                    background-color: palette(mid);
                    margin: 4px 10px;
                }
            """
            # Update panel toggle buttons for light theme
            button_style = """
                QPushButton { 
                    background-color: transparent; 
                    border: none; 
                    color: palette(window-text);
                } 
                QPushButton:hover { 
                    background-color: rgba(0, 0, 0, 0.1); 
                    border-radius: 4px; 
                } 
                QPushButton:checked { 
                    background-color: rgba(0, 120, 212, 0.3); 
                    border-radius: 4px; 
                }
            """
        
        # Apply the theme-appropriate styles
        self.menu_bar.setStyleSheet(menu_style)
        self.left_button.setStyleSheet(button_style)
        self.right_button.setStyleSheet(button_style)
        self.bottom_button.setStyleSheet(button_style)
        
        # Update title bar button colors
        self._update_title_bar_button_colors(is_dark)
    
    def _apply_container_styling(self):
        """Apply styling to the container widget."""
        # Style the container for consistent appearance
        self.container.setStyleSheet("""
            QWidget#container {
                background-color: palette(window);
            }
        """)
    
    def _is_system_dark_theme(self) -> bool:
        """Check if the system is using a dark theme."""
        # Get the system palette
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPalette
        palette = QApplication.style().standardPalette()
        window_color = palette.color(QPalette.Window)
        text_color = palette.color(QPalette.WindowText)
        
        # Calculate luminance to determine if it's a dark theme
        # Using relative luminance formula
        window_luminance = (0.299 * window_color.red() + 
                           0.587 * window_color.green() + 
                           0.114 * window_color.blue()) / 255
        
        text_luminance = (0.299 * text_color.red() + 
                         0.587 * text_color.green() + 
                         0.114 * text_color.blue()) / 255
        
        # If background is dark and text is light, it's a dark theme
        return window_luminance < 0.5 and text_luminance > 0.5
    
    def _update_title_bar_button_colors(self, is_dark: bool):
        """Update title bar button colors based on theme."""
        if is_dark:
            # Dark theme - use white icons with dark hover backgrounds
            icon_color = Qt.white
            hover_bg = QColor(80, 80, 80)
        else:
            # Light theme - use black icons with light hover backgrounds
            icon_color = Qt.black
            hover_bg = QColor(0, 0, 0, 26)
        
        # Set title bar button colors based on theme
        if hasattr(self.titleBar, 'minBtn'):
            self.titleBar.minBtn.setNormalColor(icon_color)
            self.titleBar.minBtn.setHoverColor(icon_color)
            self.titleBar.minBtn.setPressedColor(icon_color)
            self.titleBar.minBtn.setHoverBackgroundColor(hover_bg)
            
        if hasattr(self.titleBar, 'maxBtn'):
            self.titleBar.maxBtn.setNormalColor(icon_color)
            self.titleBar.maxBtn.setHoverColor(icon_color)
            self.titleBar.maxBtn.setPressedColor(icon_color)
            self.titleBar.maxBtn.setHoverBackgroundColor(hover_bg)
            
        if hasattr(self.titleBar, 'closeBtn'):
            # Close button uses the same icon color but keeps red hover background
            self.titleBar.closeBtn.setNormalColor(icon_color)
    
    def _create_sidebar_icon(self, arrow_direction) -> QIcon:
        """Create theme-aware icon for sidebar toggle buttons."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        
        # Use theme-appropriate color
        is_dark = self._is_system_dark_theme()
        icon_color = QColor("#CCCCCC") if is_dark else QColor("#666666")
        pen = QPen(icon_color)
        pen.setWidth(2)
        painter.setPen(pen)
        
        if arrow_direction == Qt.LeftArrow:
            # Left sidebar icon - bar on left with arrow
            painter.drawRect(1, 1, 6, 14)
            painter.drawLine(10, 4, 14, 8)
            painter.drawLine(10, 12, 14, 8)
        else:
            # Right sidebar icon - bar on right with arrow
            painter.drawRect(9, 1, 6, 14)
            painter.drawLine(6, 4, 2, 8)
            painter.drawLine(6, 12, 2, 8)
        
        painter.end()
        return QIcon(pixmap)
    
    def _create_bottom_panel_icon(self) -> QIcon:
        """Create theme-aware icon for bottom panel toggle button."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        
        # Use theme-appropriate color
        is_dark = self._is_system_dark_theme()
        icon_color = QColor("#CCCCCC") if is_dark else QColor("#666666")
        pen = QPen(icon_color)
        pen.setWidth(2)
        painter.setPen(pen)
        
        # Bottom panel icon - horizontal bar with down arrow
        painter.drawRect(1, 9, 14, 6)
        painter.drawLine(4, 6, 8, 2)
        painter.drawLine(12, 6, 8, 2)
        
        painter.end()
        return QIcon(pixmap)
    
    def _create_actions(self):
        """Create shared QAction objects for toolbar and menu."""
        # File actions
        self.open_action = QAction("&Open...", self)
        self.open_action.setShortcut(QKeySequence.Open)
        self.open_action.setStatusTip("Open a waveform file")
        self.open_action.triggered.connect(self.open_file)
        
        self.reload_action = QAction("&Reload", self)
        self.reload_action.setShortcut(QKeySequence("Ctrl+R"))
        self.reload_action.setStatusTip("Reload the current waveform file")
        self.reload_action.setEnabled(False)  # Disabled until a file is loaded
        self.reload_action.triggered.connect(self.reload_waveform)
        
        # View actions
        self.zoom_in_action = QAction("Zoom &In", self)
        self.zoom_in_action.setShortcut(QKeySequence("+"))
        self.zoom_in_action.setStatusTip("Zoom in on the waveform")
        self.zoom_in_action.setEnabled(False)  # Disabled until a file is loaded
        self.zoom_in_action.triggered.connect(self.wave_widget._zoom_in)
        
        self.zoom_out_action = QAction("Zoom &Out", self)
        self.zoom_out_action.setShortcut(QKeySequence("-"))
        self.zoom_out_action.setStatusTip("Zoom out of the waveform")
        self.zoom_out_action.setEnabled(False)  # Disabled until a file is loaded
        self.zoom_out_action.triggered.connect(self.wave_widget._zoom_out)
        
        self.zoom_fit_action = QAction("Zoom to &Fit", self)
        self.zoom_fit_action.setShortcut(QKeySequence("F"))
        self.zoom_fit_action.setStatusTip("Fit the entire waveform in view")
        self.zoom_fit_action.setEnabled(False)  # Disabled until a file is loaded
        self.zoom_fit_action.triggered.connect(self.wave_widget._zoom_to_fit)
        
        self.pan_left_action = QAction("Pan &Left", self)
        self.pan_left_action.setShortcut(QKeySequence("Left"))
        self.pan_left_action.setStatusTip("Pan the view left")
        self.pan_left_action.setEnabled(False)  # Disabled until a file is loaded
        self.pan_left_action.triggered.connect(self.wave_widget._pan_left)
        
        self.pan_right_action = QAction("Pan &Right", self)
        self.pan_right_action.setShortcut(QKeySequence("Right"))
        self.pan_right_action.setStatusTip("Pan the view right")
        self.pan_right_action.setEnabled(False)  # Disabled until a file is loaded
        self.pan_right_action.triggered.connect(self.wave_widget._pan_right)
        
        # Value tooltip action
        self.value_tooltip_action = QAction("Value Tooltip at Cursor", self)
        self.value_tooltip_action.setCheckable(True)
        self.value_tooltip_action.setStatusTip("Show signal values as tooltips at cursor position")
        value_tooltips_enabled = self.settings_manager.get_value_tooltips_enabled()
        self.value_tooltip_action.setChecked(value_tooltips_enabled)
        self.value_tooltip_action.triggered.connect(self._toggle_value_tooltips)
        
        # Highlight selected action
        self.highlight_selected_action = QAction("Highlight Selected", self)
        self.highlight_selected_action.setCheckable(True)
        self.highlight_selected_action.setStatusTip("Highlight selected signals in the waveform canvas")
        highlight_selected_enabled = self.settings_manager.get_highlight_selected()
        self.highlight_selected_action.setChecked(highlight_selected_enabled)
        self.highlight_selected_action.triggered.connect(self._toggle_highlight_selected)
        
        # Hierarchy levels action
        self.hierarchy_levels_action = QAction("&Hier Name Levels...", self)
        self.hierarchy_levels_action.setStatusTip("Configure hierarchical name display levels")
        self.hierarchy_levels_action.triggered.connect(self._show_hierarchy_levels_dialog)
        
        # Set icons for toolbar
        style = self.style()
        if style:
            self.open_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
            self.reload_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            self.zoom_in_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
            self.zoom_out_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
            self.pan_left_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
            self.pan_right_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            self.zoom_fit_action.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
    
    def _create_toolbar(self):
        """Create the main toolbar."""
        self.toolbar = QToolBar("Main Toolbar", self)
        self.toolbar.setObjectName("MainToolbar")  # For saving/restoring state
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        
        # Add toolbar to main layout (already inserted before splitter)
        self.main_layout.insertWidget(0, self.toolbar)
        
        # Add actions to toolbar
        self.toolbar.addAction(self.open_action)
        self.toolbar.addAction(self.reload_action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.zoom_in_action)
        self.toolbar.addAction(self.zoom_out_action)
        self.toolbar.addAction(self.zoom_fit_action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.pan_left_action)
        self.toolbar.addAction(self.pan_right_action)
    
    def _create_menus(self):
        """Create application menus."""
        menubar = self.menu_bar
        
        # File menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.reload_action)
        file_menu.addSeparator()
        file_menu.addAction("&Save Session...", self.save_session)
        file_menu.addAction("&Load Session...", self.load_session)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)
        
        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        self.drop_marker_action = QAction("&Drop Marker", self)
        self.drop_marker_action.setShortcut(QKeySequence("Ctrl+M"))
        self.drop_marker_action.triggered.connect(self._drop_marker)
        edit_menu.addAction(self.drop_marker_action)
        
        # Markers window action
        self.markers_window_action = QAction("&Markers...", self)
        self.markers_window_action.triggered.connect(self._show_markers_window)
        edit_menu.addAction(self.markers_window_action)
        
        edit_menu.addSeparator()
        
        # Navigate to Time/Clock action
        self.navigate_time_action = QAction("Navigate to &Time/Clk", self)
        self.navigate_time_action.setShortcut(QKeySequence("T"))
        self.navigate_time_action.setStatusTip("Navigate to specific timestamp or clock cycle")
        self.navigate_time_action.setEnabled(False)  # Disabled until a file is loaded
        self.navigate_time_action.triggered.connect(self.wave_widget._show_navigate_time_dialog)
        edit_menu.addAction(self.navigate_time_action)
        
        edit_menu.addSeparator()
        
        # Open Snippets in Files action
        self.open_snippets_action = QAction("Open Snippets in &Files", self)
        self.open_snippets_action.setStatusTip("Open snippets directory in file manager")
        self.open_snippets_action.triggered.connect(self._open_snippets_directory)
        edit_menu.addAction(self.open_snippets_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.zoom_in_action)
        view_menu.addAction(self.zoom_out_action)
        view_menu.addAction(self.zoom_fit_action)
        view_menu.addSeparator()
        view_menu.addAction(self.pan_left_action)
        view_menu.addAction(self.pan_right_action)
        view_menu.addSeparator()
        view_menu.addAction(self.value_tooltip_action)
        view_menu.addAction(self.highlight_selected_action)
        view_menu.addSeparator()
        view_menu.addAction(self.hierarchy_levels_action)
        view_menu.addSeparator()
        
        # UI Scaling submenu
        ui_scaling_menu = view_menu.addMenu("&UI Scaling")
        ui_scaling_group = QActionGroup(self)
        
        # Add scaling options
        scaling_options = [
            ("75%", 0.75),
            ("90%", 0.9),
            ("100%", 1.0),
            ("110%", 1.1),
            ("125%", 1.25),
            ("150%", 1.5),
            ("175%", 1.75),
            ("200%", 2.0)
        ]
        
        for label, scale in scaling_options:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(abs(scale - self.current_ui_scale) < 0.01)
            action.triggered.connect(lambda checked, s=scale: self._set_ui_scale(s))
            ui_scaling_group.addAction(action)
            ui_scaling_menu.addAction(action)
        
        view_menu.addSeparator()
        
        # Theme submenu for waveform colors
        theme_menu = view_menu.addMenu("&Wave Color Theme")
        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        
        # Add theme options
        for theme in ThemeName:
            action = QAction(theme.value, self)
            action.setCheckable(True)
            action.setChecked(theme == theme_manager.current_theme_name())
            action.triggered.connect(lambda checked, t=theme: self._set_theme(t))
            self.theme_action_group.addAction(action)
            theme_menu.addAction(action)
        
        view_menu.addSeparator()
        
        # Style submenu
        style_menu = view_menu.addMenu("&Widgets Style")
        self.style_action_group = QActionGroup(self)
        self.style_action_group.setExclusive(True)
        
        # Track current style (default or qdarkstyle)
        self.current_style_type = self.settings_manager.get_style_type()
        
        # Add default Qt styles
        available_styles = QStyleFactory.keys()
        current_style = QApplication.instance().style().objectName() if QApplication.instance() else ""
        
        for name in available_styles:
            act = QAction(name, self)
            act.setCheckable(True)
            # Check if this is the current style and we're not using qdarkstyle
            if self.current_style_type == "default" and current_style and name.lower() == current_style.lower():
                act.setChecked(True)
            act.triggered.connect(lambda checked, n=name: self._set_ui_style(n))
            self.style_action_group.addAction(act)
            style_menu.addAction(act)
        
        # Add separator before QDarkStyle options
        style_menu.addSeparator()
        
        # Add QDarkStyle options
        qdark_action = QAction("QDarkStyle (Dark)", self)
        qdark_action.setCheckable(True)
        qdark_action.setChecked(self.current_style_type == "qdarkstyle_dark")
        qdark_action.triggered.connect(lambda: self._set_qdarkstyle("dark"))
        self.style_action_group.addAction(qdark_action)
        style_menu.addAction(qdark_action)
        
        qlight_action = QAction("QDarkStyle (Light)", self)
        qlight_action.setCheckable(True)
        qlight_action.setChecked(self.current_style_type == "qdarkstyle_light")
        qlight_action.triggered.connect(lambda: self._set_qdarkstyle("light"))
        self.style_action_group.addAction(qlight_action)
        style_menu.addAction(qlight_action)
        
        view_menu.addSeparator()
        
    def reload_waveform(self):
        """Reload the current waveform file while preserving session state."""
        if not self.current_wave_file:
            show_information(self, "No File Loaded", "No waveform file is currently loaded.")
            return
            
        # Check if file still exists
        if not os.path.exists(self.current_wave_file):
            show_critical(self, "File Not Found", 
                        f"The file no longer exists:\n{self.current_wave_file}")
            self.current_wave_file = None
            self._set_waveform_actions_enabled(False)
            return
        
        # Save current session state to temporary file
        import tempfile
        from pathlib import Path
        from wavescout.persistence import save_session, load_session
        
        if self.wave_widget.session and self.wave_widget.session.waveform_db:
            try:
                # Create temporary file for session
                tmp_fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix='wavescout_reload_')
                temp_session_path = Path(tmp_path)
                os.close(tmp_fd)  # Close the file descriptor as we'll write using save_session
                
                # Save current session state
                save_session(self.wave_widget.session, temp_session_path)
                
                # Reload the waveform with preserved session
                self.statusBar().showMessage(f"Reloading {os.path.basename(self.current_wave_file)} with preserved session...")
                
                # Load the session (which will reload the waveform and restore state)
                self.load_session_file(str(temp_session_path))
                
                # Note: Clean up will happen after the async load completes
                # Store the temp path to delete it after loading
                self._temp_reload_session_path = temp_session_path
                    
            except Exception as e:
                # If session preservation fails, fall back to regular reload
                show_warning(self, "Session Preservation Failed", 
                           f"Failed to preserve session state. Performing regular reload.\n{str(e)}")
                self.statusBar().showMessage(f"Reloading {os.path.basename(self.current_wave_file)}...")
                self.load_file(self.current_wave_file)
        else:
            # No session to preserve, just reload the file
            self.statusBar().showMessage(f"Reloading {os.path.basename(self.current_wave_file)}...")
            self.load_file(self.current_wave_file)
    
    def _set_waveform_actions_enabled(self, enabled: bool):
        """Enable or disable waveform-related actions."""
        self.reload_action.setEnabled(enabled and self.current_wave_file is not None)
        self.zoom_in_action.setEnabled(enabled)
        self.zoom_out_action.setEnabled(enabled)
        self.zoom_fit_action.setEnabled(enabled)
        self.pan_left_action.setEnabled(enabled)
        self.pan_right_action.setEnabled(enabled)
        self.navigate_time_action.setEnabled(enabled)
    
    def open_file(self):
        """Open a waveform file using file dialog."""

        # Get file path from user
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Waveform File",
            "",
            "Waveform Files (*.vcd *.fst *.ghw);;VCD Files (*.vcd);;FST Files (*.fst);;GHDL Files (*.ghw);;All Files (*)"
        )
        
        if file_path:
            # Use QTimer to defer loading, allowing the dialog to close first
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.load_file(file_path))
            
    def load_file(self, file_path: str):
        """Load a waveform file asynchronously using thread pool."""
        tprint(f"Loading file: {file_path}")
        # Store the file path for reload functionality
        self.current_wave_file = file_path

        # Show loading status
        file_name = os.path.basename(file_path)
        
        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            f"Loading {file_name}...",
            "Cancel",
            0,
            0,  # Indeterminate progress
            self
        )
        self.progress_dialog.setWindowTitle("Loading Waveform")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)  # Show immediately
        self.progress_dialog.setCancelButton(None)  # No cancel for now
        self.progress_dialog.show()
        
        # Update status bar
        self.statusBar().showMessage(f"Loading {file_name}...")
        
        # Create and run loader with backend preference, but defer start slightly to ensure dialog paints first
        loader = LoaderRunnable(create_sample_session, file_path)
        loader.signals.finished.connect(self._on_waveform_load_finished)
        loader.signals.error.connect(self._on_waveform_load_error)
        # Process events so the dialog is shown before starting heavy work
        QApplication.processEvents()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.thread_pool.start(loader))
        
    def _on_waveform_load_finished(self, session):
        """Handle successful waveform load."""
        tprint(f"Waveform loaded successfully")
        # Store session for later use
        self._loading_state.pending_session = session
        self._finalize_waveform_load()
        
    def _on_waveform_load_error(self, error_msg):
        """Handle waveform load error."""
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
        # Clear the current file on error
        self.current_wave_file = None
        self._set_waveform_actions_enabled(False)
            
        self.on_load_error(error_msg)
        
    def on_load_finished(self, session):
        """Handle successful file load."""
        self.wave_widget.setSession(session)
        
        
        # Get filename from the session's waveform database (file_path is optional property)
        if session.waveform_db:
            file_path = getattr(session.waveform_db, 'file_path', None)
            if file_path:
                file_name = Path(file_path).name
            else:
                file_name = None
            # Include timescale info if available
            if file_name:
                if session.timescale:
                    timescale_str = f"{session.timescale.factor}{session.timescale.unit.value}"
                    self.statusBar().showMessage(f"Loaded: {file_name} (Timescale: {timescale_str})")
                else:
                    self.statusBar().showMessage(f"Loaded: {file_name}")
                # Print confirmation for CLI/integration tests
                if file_path:
                    try:
                        tprint(f"Successfully loaded waveform: {file_path}")
                    except Exception:
                        pass
            else:
                self.statusBar().showMessage("File loaded successfully")
        else:
            self.statusBar().showMessage("File loaded successfully")
            
        # Defer heavy UI updates to allow UI to remain responsive
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        
        def update_design_tree():
            if session.waveform_db:
                # Show progress for tree building
                tree_progress = QProgressDialog(
                    "Building design hierarchy...",
                    None,  # No cancel button
                    0,
                    0,
                    self
                )
                tree_progress.setWindowTitle("Processing")
                tree_progress.setWindowModality(Qt.WindowModal)
                tree_progress.show()
                QApplication.processEvents()
                
                self.design_tree_view.set_waveform_db(session.waveform_db)
                    
                tree_progress.close()
                
                # Close the main progress dialog now that everything is done
                if self.progress_dialog:
                    self.progress_dialog.close()
                    self.progress_dialog = None
                
        # Use timer to defer tree update, allowing UI to update first
        QTimer.singleShot(100, update_design_tree)
        
    def on_load_error(self, error_msg):
        """Handle file load error."""
        show_critical(self, "Load Error", f"Failed to load file:\n{error_msg}")
        self.statusBar().showMessage("Load failed")
        # If running in test/integration mode, exit with error
        if getattr(self, 'exit_after_load', False):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: QApplication.exit(1))
            
    def load_vcd(self, path: str):
        """Load a VCD file synchronously."""
        self.load_file(path)
                
    def save_session(self):
        """Save the current session to a JSON file."""
        if not self.wave_widget.session:
            show_warning(self, "No Session", "No session to save.")
            return
            
        # Get file path from user
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Session",
            "",
            "Session Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                save_session(self.wave_widget.session, Path(file_path))
                self.statusBar().showMessage(f"Session saved to: {Path(file_path).name}")
            except Exception as e:
                show_critical(self, "Save Error", f"Failed to save session:\n{str(e)}")
                
    def load_session(self):
        """Load a session from a JSON file using file dialog."""
        # Force garbage collection before opening dialog
        import gc
        gc.collect()
        
        # Get file path from user
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Session",
            "",
            "Session Files (*.json);;All Files (*)"
        )
        
        if file_path:
            # Use QTimer to defer loading, allowing the dialog to close first
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.load_session_file(file_path))
    
    def load_session_file(self, file_path: str):
        """Load a session from a specified file path."""
        if not os.path.exists(file_path):
            tprint(f"Error: Session file not found: {file_path}")
            return
            
        # Clear the design tree before loading new session
        self.design_tree_view.set_waveform_db(None)
        
        # Get filename for progress dialog
        file_name = os.path.basename(file_path)
        
        # Create progress dialog
        self.progress_dialog = QProgressDialog(
            f"Loading session {file_name}...",
            "Cancel",
            0,
            0,  # Indeterminate progress
            self
        )
        self.progress_dialog.setWindowTitle("Loading Session")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)  # Show immediately
        self.progress_dialog.setCancelButton(None)  # No cancel for now
        self.progress_dialog.show()
        
        # Update status bar
        self.statusBar().showMessage(f"Loading session {file_name}...")
        
        # Store file path for later use
        self._loading_session_path = file_path
        
        # Create and run loader with backend preference, but defer start slightly to ensure dialog paints first
        loader = LoaderRunnable(load_session, Path(file_path))
        loader.signals.finished.connect(self._on_session_load_finished)
        loader.signals.error.connect(self._on_session_load_error)
        # Process events so the dialog is shown before starting heavy work
        QApplication.processEvents()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self.thread_pool.start(loader))
        
    def _on_session_load_finished(self, session):
        """Handle successful session load."""
        # Store session for later use
        self._loading_state.pending_loaded_session = session
        self._finalize_session_load()
            
    def _on_session_load_error(self, error_msg):
        """Handle session load error."""
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # Disable waveform actions on error
        self._set_waveform_actions_enabled(False)
            
        session_file = self._loading_state.session_path or 'unknown'
        error_msg = f"Failed to load session from {session_file}:\n{error_msg}"
        tprint(f"Error: {error_msg}")
        show_critical(self, "Load Error", error_msg)
        self.statusBar().showMessage("Session load failed")
        
        # Clean up loading state
        self._loading_state.clear()
    
    def _finalize_session_load(self):
        """Complete the session loading process after signals are preloaded."""
        if self._loading_state.pending_loaded_session is None:
            return
            
        session = self._loading_state.pending_loaded_session
        self._loading_state.pending_loaded_session = None
        
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # Set the session on the widget
        self.wave_widget.setSession(session)
        
        # Store the session file path
        if self._loading_state.session_path is not None:
            session_file = self._loading_state.session_path
            self.statusBar().showMessage(f"Session loaded from: {Path(session_file).name}")
            tprint(f"Successfully loaded session from: {session_file}")
        
        # Clean up loading state
        self._loading_state.clear()
        
        # Update design tree if we have a waveform
        if session.waveform_db:
            # Defer heavy UI updates to allow UI to remain responsive
            from PySide6.QtCore import QTimer

            def update_design_tree():
                """Update design tree with loaded waveform."""
                tprint(f"QTimer callback: updating design tree")
                if session.waveform_db and self.design_tree_view:
                    self.design_tree_view.set_waveform_db(session.waveform_db)
                tprint(f"QTimer callback: design tree updated")

            tprint(f"Scheduling design tree update via QTimer (10ms delay)")
            QTimer.singleShot(10, update_design_tree)

    def _expand_tree_levels(self, tree_view: QTreeView, levels: int, parent=None):
        """Recursively expand tree to specified number of levels."""
        model = tree_view.model()
        if not model:
            return
            
        if parent is None:
            # Expand from root level
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                if index.isValid():
                    tree_view.expand(index)
                    if levels > 1:
                        self._expand_tree_levels(tree_view, levels - 1, index)
        else:
            if levels <= 0:
                return
                
            for row in range(model.rowCount(parent)):
                index = model.index(row, 0, parent)
                if index.isValid():
                    tree_view.expand(index)
                    self._expand_tree_levels(tree_view, levels - 1, index)


    def _on_signals_selected(self, signal_nodes):
        """Handle signals selected from the design tree view."""
        if not self.wave_widget.session:
            return
        
        # Extract handles from signal nodes
        handles = []
        for node in signal_nodes:
            if node.handle is not None:
                handles.append(node.handle)
        
        if not handles:
            # No valid handles, just add nodes directly
            for node in signal_nodes:
                self._add_node_to_session(node)
            return
        
        waveform_db = self.wave_widget.session.waveform_db
        if not waveform_db:
            return
            
        # Need to load signals asynchronously using new system
        # Add nodes immediately with signal=None
        for node in signal_nodes:
            self._add_node_to_session(node)

    def _extract_session_handles(self, session):
        """Extract all signal handles from a session.
        
        Args:
            session: WaveformSession to extract handles from
            
        Returns:
            List of signal handles
        """
        if not session:
            return []
            
        handles = []
        
        def extract_handles(nodes):
            """Recursively extract handles from nodes."""
            for node in nodes:
                if node.handle is not None:
                    handles.append(node.handle)
                if hasattr(node, 'children') and node.children:
                    extract_handles(node.children)
        
        extract_handles(session.root_nodes)
        return handles
    
    def _on_session_signals_preloaded(self):
        """Handle completion of session signal preloading."""
        self._finalize_waveform_load()
    
    def _on_session_preload_error(self, error_msg):
        """Handle error during session signal preloading."""
        tprint(f"Warning: Failed to preload session signals: {error_msg}")
        # Continue anyway - signals will load lazily if needed
        self._finalize_waveform_load()
    
    def _finalize_waveform_load(self):
        """Complete the waveform loading process after signals are preloaded."""
        if self._loading_state.pending_session is None:
            return
            
        session = self._loading_state.pending_session
        self._loading_state.pending_session = None
        
        # Close progress dialog
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
        # Enable waveform-related actions
        self._set_waveform_actions_enabled(True)
        
        # Set the session on the widget
        self.wave_widget.setSession(session)
        
        # Get filename and update status
        if session.waveform_db:
            file_path = session.waveform_db.file_path
            if file_path:
                self.current_wave_file = Path(file_path)
                self.setWindowTitle(f"WaveScout - {Path(file_path).name}")
                self.statusBar().showMessage(f"Loaded: {Path(file_path).name}")
                tprint(f"Successfully loaded waveform: {file_path}")
            
            # Update design tree if we have a waveform
            # Defer heavy UI updates to allow UI to remain responsive
            from PySide6.QtCore import QTimer

            def update_design_tree():
                """Update design tree with loaded waveform."""
                tprint(f"QTimer callback: updating design tree")
                if session.waveform_db and self.design_tree_view:
                    self.design_tree_view.set_waveform_db(session.waveform_db)
                tprint(f"QTimer callback: design tree updated")

                # Load CLI snippets after design tree is ready
                if self._loading_state.cli_snippets:
                    tprint(f"Scheduling CLI snippets load (100ms delay)")
                    QTimer.singleShot(100, lambda: self._load_cli_snippets(self._loading_state.cli_snippets))
                else:
                    # Check if we should exit after loading (when no snippets to load)
                    if getattr(self, 'exit_after_load', False):
                        def exit_after_load():
                            import sys
                            tprint("Successfully loaded waveform: " + str(self.current_wave_file))
                            sys.stdout.flush()
                            QApplication.instance().quit()
                        QTimer.singleShot(200, exit_after_load)

            tprint(f"Scheduling design tree update via QTimer (10ms delay)")
            QTimer.singleShot(10, update_design_tree)
    
    # Legacy async loading - replaced by new event-driven async system
    # This method is kept for backward compatibility but should not be used
    def _load_signals_async(self, signal_nodes, handles):
        """[DEPRECATED] Load signals asynchronously with progress dialog.

        This method has been replaced by the new event-driven async loading system.
        The new system uses WaveformDB.load_signals_async() and event bus for
        proper thread-safe signal loading.

        Args:
            signal_nodes: List of SignalNode objects to add after loading
            handles: List of signal handles to preload
        """
        # For backward compatibility, just add nodes immediately
        # The new async system will handle the actual loading
        waveform_db = self.wave_widget.session.waveform_db
        if not waveform_db:
            return

        # Just add the nodes - signals will load asynchronously via new system
        for node in signal_nodes:
            self._add_node_to_session(node)

        # Trigger async loading through new system if available
        if hasattr(waveform_db, 'load_signals_async'):
            waveform_db.load_signals_async(handles)
    
    def _on_signals_loaded(self, result=None):
        """Handle successful signal loading.
        
        Args:
            result: Optional result from LoaderRunnable (not used here)
        """
        # Close progress dialog
        if self.signal_loading_dialog is not None:
            self.signal_loading_dialog.close()
            self.signal_loading_dialog = None
        
        # Add the pending nodes to session
        if self._loading_state.pending_signal_nodes:
            for node in self._loading_state.pending_signal_nodes:
                self._add_node_to_session(node)
            self._loading_state.pending_signal_nodes = []
        
        # Update status
        self.statusBar().showMessage("Signals loaded successfully", 2000)
    
    def _on_signal_load_error(self, error_msg):
        """Handle signal loading error."""
        # Close progress dialog
        if self.signal_loading_dialog is not None:
            self.signal_loading_dialog.close()
            self.signal_loading_dialog = None
        
        # Clear pending nodes
        self._loading_state.pending_signal_nodes = []
        
        # Show error message
        show_critical(self, "Signal Loading Error", error_msg)
        self.statusBar().showMessage("Failed to load signals", 3000)
        
    def _add_node_to_session(self, new_node):
        """Add a node to the waveform session after the last selected node."""
        session = self.wave_widget.session
        model = self.wave_widget.model
        
        if session.selected_nodes:
            # Find the last selected node
            last_selected = session.selected_nodes[-1]
            
            # Find its parent and position
            if last_selected.parent:
                # Add after the selected node in its parent's children
                parent = last_selected.parent
                idx = parent.children.index(last_selected) + 1
                parent.children.insert(idx, new_node)
                new_node.parent = parent
            else:
                # It's a root node, add after it in root_nodes
                idx = session.root_nodes.index(last_selected) + 1
                session.root_nodes.insert(idx, new_node)
        else:
            # No selection, add to end of root nodes
            session.root_nodes.append(new_node)
            
        # Notify the model about the change
        if model:
            model.layoutChanged.emit()
            
        self.statusBar().showMessage(f"Added signal: {new_node.name}")
    
    def _drop_marker(self):
        """Add a marker at the current cursor position."""
        if self.wave_widget.controller and self.wave_widget.session:
            # Find the first available marker slot
            for i in range(RENDERING.MAX_MARKERS):
                marker = self.wave_widget.controller.get_marker(i)
                if not marker:
                    self.wave_widget.controller.add_marker(i, self.wave_widget.session.cursor_time)
                    self.statusBar().showMessage(f"Marker {chr(65 + i)} added at cursor position", 3000)
                    break
            else:
                self.statusBar().showMessage("All marker slots are in use", 3000)
    
    def _show_markers_window(self):
        """Show the markers management window."""
        from wavescout.markers_window import MarkersWindow
        
        if self.wave_widget.controller and self.wave_widget.session:
            dialog = MarkersWindow(self.wave_widget.controller, self)
            dialog.exec()
    
    def _open_snippets_directory(self):
        """Open the snippets directory in the system file manager."""
        from wavescout.snippet_manager import SnippetManager
        
        # Get the snippets directory from SnippetManager
        snippet_manager = SnippetManager()
        snippets_dir = snippet_manager._snippets_dir
        
        # Ensure the directory exists
        snippets_dir.mkdir(parents=True, exist_ok=True)
        
        # Open the directory in the system file manager
        system = platform.system()
        try:
            if system == "Windows":
                os.startfile(str(snippets_dir))
            elif system == "Darwin":  # macOS
                subprocess.run(["open", str(snippets_dir)], check=True)
            else:  # Linux and other Unix-like systems
                # Try different file managers
                file_managers = ["xdg-open", "nautilus", "dolphin", "thunar", "pcmanfm"]
                for fm in file_managers:
                    try:
                        subprocess.run([fm, str(snippets_dir)], check=True)
                        break
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        continue
                else:
                    # If no file manager worked, show error
                    show_warning(
                        self,
                        "Could not open file manager",
                        f"Unable to open file manager.\n\nSnippets directory:\n{snippets_dir}"
                    )
        except Exception as e:
            show_warning(
                self,
                "Error opening snippets directory",
                f"Failed to open snippets directory:\n{e}\n\nPath:\n{snippets_dir}"
            )
    
    def _set_ui_scale(self, scale: float):
        """Set the UI scaling factor."""
        # Save the scale preference
        self.settings_manager.set_ui_scale(scale)
        
        # Show message
        self.statusBar().showMessage(f"UI Scale: {int(scale * 100)}%", 2000)
        
        # Inform user that restart is required
        result = show_question(
            self,
            "UI Scaling Changed",
            f"UI scaling set to {int(scale * 100)}%.\n\n"
            "The application needs to restart for the scaling to take effect.\n"
            "Would you like to restart now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if result == QMessageBox.Yes:
            # Restart the application
            import subprocess
            subprocess.Popen([sys.executable] + sys.argv)
            QApplication.quit()
    
    def _apply_ui_scale(self, scale: float):
        """Apply the UI scaling factor to the application."""
        # Store current scale for reference
        self.current_ui_scale = scale
        
        # The actual scaling will be applied through environment variable
        # on next application start

    def _set_theme(self, theme_name: ThemeName):
        """Set the waveform color theme and persist the choice."""
        # Apply the theme
        theme_manager.set_theme(theme_name)
        
        # Save the theme preference
        theme_manager.save_to_settings(self.settings, theme_name)
        
        # Update status bar
        self.statusBar().showMessage(f"Theme changed to: {theme_name.value}", 2000)
    
    def _toggle_value_tooltips(self, checked: bool):
        """Toggle value tooltips at cursor and persist the setting."""
        # Apply the setting to the wave widget
        self.wave_widget.set_value_tooltips_enabled(checked)
        
        # Save the preference
        self.settings_manager.set_value_tooltips_enabled(checked)
        
        # Update status bar
        status = "enabled" if checked else "disabled"
        self.statusBar().showMessage(f"Value tooltips {status}", 2000)
    
    def _toggle_highlight_selected(self, checked: bool):
        """Toggle highlighting of selected signals and persist the setting."""
        # Apply the setting to the wave widget
        self.wave_widget.set_highlight_selected(checked)
        
        # Save the preference
        self.settings_manager.set_highlight_selected(checked)
        
        # Update status bar
        status = "enabled" if checked else "disabled"
        self.statusBar().showMessage(f"Highlight selected {status}", 2000)
    
    def _show_hierarchy_levels_dialog(self):
        """Show the hierarchy levels configuration dialog."""
        from wavescout.hierarchy_levels_dialog import HierarchyLevelsDialog
        
        dialog = HierarchyLevelsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # The dialog handles saving the setting and emitting the signal
            # Just show confirmation message
            from wavescout.settings_manager import SettingsManager
            settings_manager = SettingsManager()
            levels = settings_manager.get_hierarchy_levels()
            if levels == 0:
                self.statusBar().showMessage("Showing full hierarchical names", 2000)
            else:
                self.statusBar().showMessage(f"Showing last {levels} hierarchy level(s)", 2000)
    
    def _on_theme_changed(self, color_scheme):
        """Handle theme change signal by repainting widgets."""
        # Update existing signal colors to use new theme default
        if self.wave_widget and self.wave_widget.session is not None:
            self._update_signal_colors_to_theme()
        
        # Update title bar and button styling based on new theme
        self._apply_frameless_styling()
        
        # Recreate icons with new theme colors
        self.left_button.setIcon(self._create_sidebar_icon(Qt.LeftArrow))
        self.right_button.setIcon(self._create_sidebar_icon(Qt.RightArrow))
        self.bottom_button.setIcon(self._create_bottom_panel_icon())
        
        # Trigger repaint of all widgets
        if self.wave_widget:
            self.wave_widget.update_all_views()
        
        # Update design tree view if it exists
        if self.design_tree_view is not None:
            self.design_tree_view.update()
    
    def _on_system_palette_changed(self):
        """Handle system palette changes (e.g., when user toggles Windows dark mode)."""
        # Reapply theme-aware styling when system palette changes
        self._apply_frameless_styling()
        
        # Recreate icons with new theme colors
        self.left_button.setIcon(self._create_sidebar_icon(Qt.LeftArrow))
        self.right_button.setIcon(self._create_sidebar_icon(Qt.RightArrow))
        self.bottom_button.setIcon(self._create_bottom_panel_icon())
    
    def _update_signal_colors_to_theme(self):
        """Update all signal colors that are using the old default to use the new theme default."""
        from wavescout import config
        new_default = config.COLORS.DEFAULT_SIGNAL
        
        # Walk through all signals in the session and update colors
        if not self.wave_widget or not self.wave_widget.session:
            return
            
        def update_node_colors(node):
            """Recursively update node colors."""
            # Update this node's color if it's using a default
            # (We check common default colors from all themes)
            default_colors = ["#33C3F0", "#56B6C2", "#8BE9FD"]
            if hasattr(node, 'format') and node.format.color in default_colors:
                node.format.color = new_default
            
            # Process children for group nodes
            if isinstance(node, GroupNode):
                for child in node.children:
                    update_node_colors(child)
        
        # Update all root nodes
        for node in self.wave_widget.session.root_nodes:
            update_node_colors(node)

    def _set_ui_style(self, style_name: str):
        """Set the Qt widget style at runtime and persist the choice."""
        if not style_name:
            return
        if style_name not in QStyleFactory.keys():
            show_warning(self, "Style Not Available", f"The style '{style_name}' is not available on this platform.")
            return
        app = QApplication.instance()
        if not app:
            return
        
        # Clear any QDarkStyle stylesheet first
        app.setStyleSheet("")
        
        # Apply the style
        style = QStyleFactory.create(style_name)
        if style is None:
            show_warning(self, "Style Error", f"Failed to create style '{style_name}'.")
            return
        app.setStyle(style)
        
        # Persist user choice
        self.settings_manager.set_ui_style(style_name)
        self.current_style_type = "default"
        
        # Feedback to user
        self.statusBar().showMessage(f"Style: {style_name}", 2000)
    
    def _set_qdarkstyle(self, palette: str):
        """Apply QDarkStyle with the specified palette."""
        app = QApplication.instance()
        if not app:
            return
        
        try:
            if palette == "dark":
                stylesheet = qdarkstyle.load_stylesheet(palette=qdarkstyle.DarkPalette)
                style_type = "qdarkstyle_dark"
                msg = "QDarkStyle (Dark)"
            else:  # light
                stylesheet = qdarkstyle.load_stylesheet(palette=qdarkstyle.LightPalette)
                style_type = "qdarkstyle_light"
                msg = "QDarkStyle (Light)"
            
            # Apply the stylesheet
            app.setStyleSheet(stylesheet)
            
            # Persist user choice
            self.settings_manager.set_style_type(style_type)
            self.current_style_type = style_type
            
            # Feedback to user
            self.statusBar().showMessage(f"Style: {msg}", 2000)
            
        except Exception as e:
            show_warning(self, "Style Error", f"Failed to apply QDarkStyle: {str(e)}")
            # Fall back to default style
            app.setStyleSheet("")
            self.settings_manager.set_style_type("default")
            self.current_style_type = "default"
        # Optionally refresh icons to the new style's standard icons
        new_style = self.style()
        if new_style:
            self.open_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
            self.reload_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            self.zoom_in_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
            self.zoom_out_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
            self.pan_left_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
            self.pan_right_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            self.zoom_fit_action.setIcon(new_style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton))
    
    def _on_snippet_instantiate(self, snippet):
        """Handle snippet instantiation request from browser."""
        from wavescout.snippet_dialogs import InstantiateSnippetDialog
        from wavescout.data_model import GroupNode
        
        # Get current waveform database
        waveform_db = None
        if self.wave_widget.session:
            waveform_db = self.wave_widget.session.waveform_db
        
        # Show instantiation dialog
        dialog = InstantiateSnippetDialog(snippet, waveform_db, self)
        
        if dialog.exec() == InstantiateSnippetDialog.DialogCode.Accepted:
            remapped_nodes = dialog.get_remapped_nodes()
            group_name = dialog.get_group_name()  # Get custom group name
            handles_to_load = dialog.get_handles_to_load()  # Get handles that need async loading
            if remapped_nodes and self.wave_widget.controller:
                # Get currently selected node to insert after
                after_id = None
                if self.wave_widget.session and self.wave_widget.session.selected_nodes:
                    after_id = self.wave_widget.session.selected_nodes[-1].instance_id

                # Wrap the snippet nodes in a group with custom name
                group_node = GroupNode(
                    name=group_name,  # Use custom group name from dialog
                    children=remapped_nodes,
                    is_expanded=True
                )

                # Set parent references for children
                for child in remapped_nodes:
                    child.parent = group_node

                # Instantiate the snippet as a single group
                success = self.wave_widget.controller.instantiate_snippet(
                    [group_node],  # Pass as single-element list containing the group
                    after_id
                )

                # NOW trigger async loading after nodes are in the session tree
                if success and handles_to_load and self.wave_widget.session and self.wave_widget.session.waveform_db:
                    if hasattr(self.wave_widget.session.waveform_db, 'load_signals_async'):
                        self.wave_widget.session.waveform_db.load_signals_async(handles_to_load)
                
                if success:
                    QMessageBox.information(
                        self, "Success",
                        f"Snippet instantiated successfully."
                    )
                else:
                    QMessageBox.critical(
                        self, "Error",
                        "Failed to instantiate snippet."
                    )
    
    def _load_cli_snippets(self, snippet_names: list[str]) -> None:
        """Load and instantiate CLI snippets using exact signal names from JSON."""
        import sys
        from wavescout.snippet_dialogs import InstantiateSnippetDialog
        from wavescout.snippet_manager import SnippetManager
        from wavescout.data_model import GroupNode
        
        manager = SnippetManager()
        waveform_db = self.wave_widget.session.waveform_db
        
        for name in snippet_names:
            # Load snippet from file (reuse existing loading)
            snippet = manager.load_snippet_file(name)
            if not snippet:
                tprint(f"Error: Snippet file not found: {name}")
                sys.exit(1)
                return  # This return is for testing - sys.exit will normally terminate
            
            # Build full paths by concatenating parent with relative names
            full_path_nodes = []
            for node in snippet.nodes:
                full_path_nodes.append(InstantiateSnippetDialog.build_full_paths(node, snippet.parent_name))
            
            # Validate and resolve handles
            try:
                validated_nodes, handles_to_load = InstantiateSnippetDialog.validate_and_resolve_nodes(
                    full_path_nodes, waveform_db
                )
            except ValueError as e:
                # Enhance error message to include snippet name
                tprint(f"Error in snippet '{name}': {e}")
                sys.exit(1)

            # Create group to wrap snippet (reuse logic from _on_snippet_instantiate)
            group_node = GroupNode(
                name=snippet.name,
                children=validated_nodes,
                is_expanded=True
            )
            for child in validated_nodes:
                child.parent = group_node

            # Instantiate using existing controller method
            if not self.wave_widget.controller.instantiate_snippet([group_node]):
                tprint(f"Error: Failed to instantiate snippet: {name}")
                sys.exit(1)

            # NOW schedule async loading after nodes are in the session tree
            if handles_to_load and hasattr(waveform_db, 'load_signals_async'):
                waveform_db.load_signals_async(handles_to_load)

            tprint(f"Successfully loaded snippet: {name}")
        
        # Check if we should exit after loading
        if getattr(self, 'exit_after_load', False):
            import sys
            tprint("Successfully loaded waveform: " + str(self.current_wave_file))
            sys.stdout.flush()
            QApplication.instance().quit()
    
    def _connect_panel_toggles(self):
        """Connect panel toggle buttons to their respective methods."""
        self.left_button.clicked.connect(self.toggle_left_sidebar)
        self.right_button.clicked.connect(self.toggle_right_sidebar)
        self.bottom_button.clicked.connect(self.toggle_bottom_panel)
    
    def toggle_left_sidebar(self):
        """Toggle left sidebar visibility."""
        if self.left_panel.isVisible():
            self.left_panel.hide()
            # Update splitter sizes
            sizes = self.horizontal_splitter.sizes()
            if len(sizes) >= 3:
                # Transfer left panel space to center
                sizes[1] += sizes[0]
                sizes[0] = 0
                self.horizontal_splitter.setSizes(sizes)
        else:
            self.left_panel.show()
            # Restore default size or saved size
            sizes = self.horizontal_splitter.sizes()
            if len(sizes) >= 3:
                left_width = self.settings_manager.get_panel_size("left_width")
                # Reduce center panel to make room
                if sizes[1] > left_width:
                    sizes[1] -= left_width
                    sizes[0] = left_width
                else:
                    # Distribute space proportionally
                    total = sum(sizes)
                    sizes[0] = left_width
                    remaining = total - left_width
                    if sizes[2] > 0:  # Right panel visible
                        right_ratio = sizes[2] / (sizes[1] + sizes[2]) if (sizes[1] + sizes[2]) > 0 else 0.5
                        sizes[2] = int(remaining * right_ratio)
                        sizes[1] = remaining - sizes[2]
                    else:
                        sizes[1] = remaining
                self.horizontal_splitter.setSizes(sizes)
        
        # Update button state
        self.left_button.setChecked(self.left_panel.isVisible())
        self._save_panel_states()
    
    def toggle_right_sidebar(self):
        """Toggle right sidebar visibility."""
        if self.right_panel.isVisible():
            self.right_panel.hide()
            # Update splitter sizes
            sizes = self.horizontal_splitter.sizes()
            if len(sizes) >= 3:
                # Transfer right panel space to center
                sizes[1] += sizes[2]
                sizes[2] = 0
                self.horizontal_splitter.setSizes(sizes)
        else:
            self.right_panel.show()
            # Restore default size or saved size
            sizes = self.horizontal_splitter.sizes()
            if len(sizes) >= 3:
                right_width = self.settings_manager.get_panel_size("right_width")
                # Reduce center panel to make room
                if sizes[1] > right_width:
                    sizes[1] -= right_width
                    sizes[2] = right_width
                else:
                    # Distribute space proportionally
                    total = sum(sizes)
                    sizes[2] = right_width
                    remaining = total - right_width
                    if sizes[0] > 0:  # Left panel visible
                        left_ratio = sizes[0] / (sizes[0] + sizes[1]) if (sizes[0] + sizes[1]) > 0 else 0.5
                        sizes[0] = int(remaining * left_ratio)
                        sizes[1] = remaining - sizes[0]
                    else:
                        sizes[1] = remaining
                self.horizontal_splitter.setSizes(sizes)
        
        # Update button state
        self.right_button.setChecked(self.right_panel.isVisible())
        self._save_panel_states()
    
    def toggle_bottom_panel(self):
        """Toggle bottom panel visibility."""
        if self.bottom_panel.isVisible():
            self.bottom_panel.hide()
            # Update splitter sizes
            sizes = self.vertical_splitter.sizes()
            if len(sizes) >= 2:
                # Transfer bottom panel space to top
                sizes[0] += sizes[1]
                sizes[1] = 0
                self.vertical_splitter.setSizes(sizes)
        else:
            self.bottom_panel.show()
            # Restore default size or saved size
            sizes = self.vertical_splitter.sizes()
            if len(sizes) >= 2:
                bottom_height = self.settings_manager.get_panel_size("bottom_height")
                # Reduce top area to make room
                if sizes[0] > bottom_height:
                    sizes[0] -= bottom_height
                    sizes[1] = bottom_height
                else:
                    # Minimum reasonable sizes
                    total = sum(sizes)
                    sizes[1] = min(bottom_height, total // 3)
                    sizes[0] = total - sizes[1]
                self.vertical_splitter.setSizes(sizes)
        
        # Update button state
        self.bottom_button.setChecked(self.bottom_panel.isVisible())
        self._save_panel_states()
    
    def _save_panel_states(self):
        """Save panel visibility and sizes to settings."""
        # Save visibility states
        self.settings_manager.set_panel_visible("left", self.left_panel.isVisible())
        self.settings_manager.set_panel_visible("right", self.right_panel.isVisible())
        self.settings_manager.set_panel_visible("bottom", self.bottom_panel.isVisible())
        
        # Save sizes
        h_sizes = self.horizontal_splitter.sizes()
        if len(h_sizes) >= 3:
            if h_sizes[0] > 0:
                self.settings_manager.set_panel_size("left_width", h_sizes[0])
            if h_sizes[2] > 0:
                self.settings_manager.set_panel_size("right_width", h_sizes[2])
        
        v_sizes = self.vertical_splitter.sizes()
        if len(v_sizes) >= 2 and v_sizes[1] > 0:
            self.settings_manager.set_panel_size("bottom_height", v_sizes[1])
        
        # Save full splitter states for exact restoration
        self.settings_manager.set_splitter_sizes("horizontal", h_sizes)
        self.settings_manager.set_splitter_sizes("vertical", v_sizes)
    
    def _restore_panel_states(self):
        """Restore panel visibility and sizes from settings."""
        # Check if we have saved panel settings
        has_saved_settings = self.settings_manager.has_panel_settings()
        
        # Get visibility states with defaults (True if no saved settings)
        left_visible = self.settings_manager.get_panel_visible("left")
        right_visible = self.settings_manager.get_panel_visible("right")
        bottom_visible = self.settings_manager.get_panel_visible("bottom")
        
        # Restore splitter sizes if available, or adjust defaults based on visibility
        h_sizes = self.settings_manager.get_splitter_sizes("horizontal")
        if h_sizes and len(h_sizes) == 3:
            # Convert to integers (QSettings may store as strings)
            h_sizes = [int(s) if isinstance(s, str) else s for s in h_sizes]
        else:
            # Use current sizes as base
            h_sizes = self.horizontal_splitter.sizes()
        
        v_sizes = self.settings_manager.get_splitter_sizes("vertical")
        if v_sizes and len(v_sizes) == 2:
            # Convert to integers (QSettings may store as strings)
            v_sizes = [int(s) if isinstance(s, str) else s for s in v_sizes]
        else:
            # Use current sizes as base
            v_sizes = self.vertical_splitter.sizes()
        
        # Adjust sizes based on visibility
        if not left_visible:
            h_sizes[1] += h_sizes[0]  # Add left space to center
            h_sizes[0] = 0
            self.left_panel.hide()
        else:
            self.left_panel.show()
            
        if not right_visible:
            h_sizes[1] += h_sizes[2]  # Add right space to center
            h_sizes[2] = 0
            self.right_panel.hide()
        else:
            self.right_panel.show()
            
        if not bottom_visible:
            v_sizes[0] += v_sizes[1]  # Add bottom space to top
            v_sizes[1] = 0
            self.bottom_panel.hide()
        else:
            self.bottom_panel.show()
        
        # Apply the sizes
        self.horizontal_splitter.setSizes(h_sizes)
        self.vertical_splitter.setSizes(v_sizes)
        
        # Update toggle button states to match visibility
        self.left_button.setChecked(left_visible)
        self.right_button.setChecked(right_visible)
        self.bottom_button.setChecked(bottom_visible)
    
    def resizeEvent(self, event):
        """Handle window resize events."""
        super().resizeEvent(event)
        # Resize container to fill the window below the title bar
        self.container.setGeometry(0, self.titleBar.height(), self.width(), 
                                   self.height() - self.titleBar.height())
        # Ensure title bar is properly positioned
        self.titleBar.raise_()
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Save panel states before closing
        self._save_panel_states()
        
        # Call parent implementation
        super().closeEvent(event)


def main():
    """Run the demo application."""
    # Set startup time for global timing
    startup_time = time.time()
    set_startup_time(startup_time)
    tprint("WaveScout starting...")

    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="WaveScout Waveform Viewer Demo")
    parser.add_argument("--load_session", type=str, help="Load a session file on startup")
    parser.add_argument("--load_wave", nargs='+', metavar=('WAVE_FILE', 'SNIPPET'),
                       help="Load waveform file followed by optional snippet files")
    parser.add_argument("--exit_after_load", action="store_true", help="Exit the application after loading completes (for automation/testing)")
    args = parser.parse_args()
    tprint(f"Arguments parsed")
    
    # Load saved UI scale and apply it before creating QApplication
    # We need to use SettingsManager here before QApplication exists
    tprint("Loading settings...")
    settings_manager = SettingsManager()
    saved_scale = settings_manager.get_ui_scale()

    # Set the QT_SCALE_FACTOR environment variable
    if saved_scale != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(saved_scale)
        tprint(f"UI scale set to {saved_scale}")

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    tprint("Creating QApplication...")
    app = QApplication(sys.argv)
    app.setOrganizationName("WaveScout")
    app.setApplicationName("Scout")
    
    # Apply saved UI style if available
    tprint("Applying theme...")
    style_type = settings_manager.get_style_type()

    if style_type == "qdarkstyle_dark":
        # Apply QDarkStyle dark theme
        try:
            stylesheet = qdarkstyle.load_stylesheet(palette=qdarkstyle.DarkPalette)
            app.setStyleSheet(stylesheet)
        except Exception:
            pass
    elif style_type == "qdarkstyle_light":
        # Apply QDarkStyle light theme
        try:
            stylesheet = qdarkstyle.load_stylesheet(palette=qdarkstyle.LightPalette)
            app.setStyleSheet(stylesheet)
        except Exception:
            pass
    else:
        # Apply saved Qt style
        saved_style = settings_manager.get_ui_style()
        if saved_style:
            try:
                if saved_style in QStyleFactory.keys():
                    style_obj = QStyleFactory.create(saved_style)
                    if style_obj is not None:
                        app.setStyle(style_obj)
            except Exception:
                pass
    
    # Create main window with optional session or wave file
    tprint("Creating main window...")
    window = WaveScoutMainWindow(session_file=args.load_session, wave_file=args.load_wave, exit_after_load=args.exit_after_load)
    tprint("Main window created, showing...")
    window.show()
    tprint("Main window shown")

    tprint("WaveScout - Digital Waveform Viewer")
    tprint("====================================")
    if args.load_session:
        tprint(f"- Loading session from: {args.load_session}")
    elif args.load_wave:
        wave_file = args.load_wave[0] if isinstance(args.load_wave, list) else args.load_wave
        tprint(f"- Loading waveform from: {wave_file}")
        if isinstance(args.load_wave, list) and len(args.load_wave) > 1:
            tprint(f"- With snippets: {', '.join(args.load_wave[1:])}")
    else:
        tprint("- No waveform file specified")
        tprint("- Use File -> Open to load a VCD or FST file")
    tprint("- Click on waveform to move cursor")
    tprint("- Use View menu to zoom in/out")
    tprint("- Expand/collapse signal groups in the tree")
    tprint("")

    # Run with standard Qt event loop
    tprint("Starting application event loop...")
    result = app.exec()
    tprint(f"Application closed")
    tprint(f"Total runtime: {time.time() - startup_time:.3f} seconds")


if __name__ == "__main__":
    main()
