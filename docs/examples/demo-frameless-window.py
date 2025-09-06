import sys
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                              QHBoxLayout, QPushButton, QLabel, QTextEdit, 
                              QListWidget, QTabWidget, QSlider, QCheckBox,
                              QRadioButton, QGroupBox, QProgressBar, QSpinBox,
                              QComboBox, QLineEdit, QMenuBar, QMenu,
                              QMessageBox, QFileDialog, QToolBar, QStyle,
                              QCompleter)
from PySide6.QtCore import Qt, QTimer, QSize, QStringListModel
from PySide6.QtGui import QFont, QPalette, QColor, QAction, QIcon
from qframelesswindow import FramelessWindow


class DemoWindow(FramelessWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PySide6 Frameless Window Demo")
        self.resize(1000, 700)
        
        # Add menu bar to title bar
        self.setup_menu_bar()
        
        # Create main container widget that fills the window
        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.container.setGeometry(0, self.titleBar.height(), self.width(), self.height() - self.titleBar.height())
        
        # Set up the main layout
        main_layout = QVBoxLayout(self.container)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins to fit toolbar
        
        # Add toolbar
        self.toolbar = self.create_toolbar()
        main_layout.addWidget(self.toolbar)
        
        # Create content widget with padding
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(20, 10, 20, 20)
        
        # Title label
        title_label = QLabel("PySide6 Frameless Window Demo")
        title_font = QFont("Arial", 16, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(title_label)
        
        # Create tab widget for different demo sections
        self.tab_widget = QTabWidget()
        content_layout.addWidget(self.tab_widget)
        
        # Tab 1: Basic Widgets
        self.create_basic_widgets_tab()
        
        # Tab 2: Input Widgets
        self.create_input_widgets_tab()
        
        # Tab 3: Display Widgets
        self.create_display_widgets_tab()
        
        # Bottom control buttons
        bottom_layout = QHBoxLayout()
        
        info_label = QLabel("Window controls are in the title bar above")
        info_label.setAlignment(Qt.AlignCenter)
        bottom_layout.addWidget(info_label)
        
        self.theme_btn = QPushButton("Toggle Theme (System ↔ Dark)")
        self.theme_btn.clicked.connect(self.toggle_theme)
        bottom_layout.addWidget(self.theme_btn)
        
        content_layout.addLayout(bottom_layout)
        
        # Add content widget to main layout
        main_layout.addWidget(content_widget)
        
        # Initialize with system theme
        self.is_dark_theme = False
        self.apply_system_theme()
        
        # IMPORTANT: Raise the title bar to make it visible and clickable
        self.titleBar.raise_()
    
    def setup_menu_bar(self):
        """Set up the menu bar in the title bar"""
        # Create menu bar
        menuBar = QMenuBar(self.titleBar)
        menuBar.setNativeMenuBar(False)  # Ensure it's embedded in the window
        
        # File menu
        fileMenu = QMenu("File", self)
        
        newAction = QAction("New", self)
        newAction.setShortcut("Ctrl+N")
        newAction.triggered.connect(lambda: self.show_message("New", "New file created"))
        fileMenu.addAction(newAction)
        
        openAction = QAction("Open...", self)
        openAction.setShortcut("Ctrl+O")
        openAction.triggered.connect(self.open_file)
        fileMenu.addAction(openAction)
        
        saveAction = QAction("Save", self)
        saveAction.setShortcut("Ctrl+S")
        saveAction.triggered.connect(lambda: self.show_message("Save", "File saved"))
        fileMenu.addAction(saveAction)
        
        fileMenu.addSeparator()
        
        exitAction = QAction("Exit", self)
        exitAction.setShortcut("Ctrl+Q")
        exitAction.triggered.connect(self.close)
        fileMenu.addAction(exitAction)
        
        menuBar.addMenu(fileMenu)
        
        # Edit menu
        editMenu = QMenu("Edit", self)
        
        cutAction = QAction("Cut", self)
        cutAction.setShortcut("Ctrl+X")
        cutAction.triggered.connect(lambda: self.show_message("Cut", "Cut to clipboard"))
        editMenu.addAction(cutAction)
        
        copyAction = QAction("Copy", self)
        copyAction.setShortcut("Ctrl+C")
        copyAction.triggered.connect(lambda: self.show_message("Copy", "Copied to clipboard"))
        editMenu.addAction(copyAction)
        
        pasteAction = QAction("Paste", self)
        pasteAction.setShortcut("Ctrl+V")
        pasteAction.triggered.connect(lambda: self.show_message("Paste", "Pasted from clipboard"))
        editMenu.addAction(pasteAction)
        
        menuBar.addMenu(editMenu)
        
        # View menu
        viewMenu = QMenu("View", self)
        
        fullscreenAction = QAction("Full Screen", self)
        fullscreenAction.setShortcut("F11")
        fullscreenAction.setCheckable(True)
        fullscreenAction.triggered.connect(self.toggle_fullscreen)
        viewMenu.addAction(fullscreenAction)
        
        viewMenu.addSeparator()
        
        themeAction = QAction("Toggle Theme", self)
        themeAction.setShortcut("Ctrl+T")
        themeAction.triggered.connect(self.toggle_theme)
        viewMenu.addAction(themeAction)
        
        menuBar.addMenu(viewMenu)
        
        # Help menu
        helpMenu = QMenu("Help", self)
        
        aboutAction = QAction("About", self)
        aboutAction.triggered.connect(self.show_about)
        helpMenu.addAction(aboutAction)
        
        aboutQtAction = QAction("About Qt", self)
        aboutQtAction.triggered.connect(lambda: QMessageBox.aboutQt(self))
        helpMenu.addAction(aboutQtAction)
        
        menuBar.addMenu(helpMenu)
        
        # Insert menu bar into title bar layout
        # Add it to the left side of the title bar
        self.titleBar.layout().insertWidget(0, menuBar, 0, Qt.AlignLeft)
        
        # Add stretch to center the search bar
        self.titleBar.layout().insertStretch(1, 1)
        
        # Add search bar to title bar (centered, following MS design guidelines)
        self.setup_search_bar()
        
        # Add stretch to push window controls to the right
        self.titleBar.layout().insertStretch(3, 1)
    
    def setup_search_bar(self):
        """Set up the search bar in the title bar following MS design guidelines"""
        # Create search container widget
        search_container = QWidget()
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(10, 0, 10, 0)
        search_layout.setSpacing(5)
        
        # Create search input field
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search (Ctrl+E)")
        self.search_input.setMinimumWidth(250)
        self.search_input.setMaximumWidth(400)
        
        # Style the search input to match Windows 11 design
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 6px 12px;
                border-radius: 4px;
                font-size: 13px;
            }
        """)
        
        # Add auto-completion
        self.setup_search_completer()
        
        # Connect search functionality
        self.search_input.returnPressed.connect(self.perform_search)
        
        # Add keyboard shortcut
        search_shortcut = QAction(self)
        search_shortcut.setShortcut("Ctrl+E")
        search_shortcut.triggered.connect(lambda: self.search_input.setFocus())
        self.addAction(search_shortcut)
        
        # Alternative shortcut Ctrl+K (VS Code style)
        search_shortcut2 = QAction(self)
        search_shortcut2.setShortcut("Ctrl+K")
        search_shortcut2.triggered.connect(lambda: self.search_input.setFocus())
        self.addAction(search_shortcut2)
        
        # Add search input to layout
        search_layout.addWidget(self.search_input)
        
        # Insert search bar into title bar in the center position
        self.titleBar.layout().insertWidget(2, search_container, 0, Qt.AlignVCenter)
    
    def setup_search_completer(self):
        """Set up auto-completion for search"""
        # Sample search suggestions
        suggestions = [
            "Basic Widgets",
            "Input Widgets", 
            "Display Widgets",
            "Button",
            "Checkbox",
            "Radio Button",
            "Progress Bar",
            "Text Input",
            "Slider",
            "Combo Box",
            "List Widget",
            "Theme Settings",
            "Dark Mode",
            "Light Mode",
            "File Menu",
            "Edit Menu",
            "View Menu",
            "Help",
            "About"
        ]
        
        completer = QCompleter(suggestions)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(completer)
    
    def perform_search(self):
        """Perform search action"""
        search_text = self.search_input.text().strip()
        if search_text:
            # For demonstration, we'll show what was searched
            self.show_message("Search", f"Searching for: '{search_text}'")
            
            # In a real application, this would:
            # - Search through content
            # - Navigate to results
            # - Highlight matches
            # - Show results panel
            
            # Clear search after demonstration
            self.search_input.clear()
    
    def create_toolbar(self):
        """Create and return the main toolbar"""
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        
        # Get style for standard icons
        style = self.style()
        
        # New action
        newAction = QAction(style.standardIcon(QStyle.SP_FileIcon), "New", self)
        newAction.setStatusTip("Create a new file")
        newAction.setToolTip("Create a new file (Ctrl+N)")
        newAction.triggered.connect(lambda: self.show_message("New", "New file created"))
        toolbar.addAction(newAction)
        
        # Open action
        openAction = QAction(style.standardIcon(QStyle.SP_DirOpenIcon), "Open", self)
        openAction.setStatusTip("Open a file")
        openAction.setToolTip("Open a file (Ctrl+O)")
        openAction.triggered.connect(self.open_file)
        toolbar.addAction(openAction)
        
        # Save action
        saveAction = QAction(style.standardIcon(QStyle.SP_DialogSaveButton), "Save", self)
        saveAction.setStatusTip("Save the file")
        saveAction.setToolTip("Save the file (Ctrl+S)")
        saveAction.triggered.connect(lambda: self.show_message("Save", "File saved"))
        toolbar.addAction(saveAction)
        
        toolbar.addSeparator()
        
        # Cut action
        cutAction = QAction(style.standardIcon(QStyle.SP_LineEditClearButton), "Cut", self)
        cutAction.setStatusTip("Cut to clipboard")
        cutAction.setToolTip("Cut to clipboard (Ctrl+X)")
        cutAction.triggered.connect(lambda: self.show_message("Cut", "Cut to clipboard"))
        toolbar.addAction(cutAction)
        
        # Copy action
        copyAction = QAction(style.standardIcon(QStyle.SP_FileDialogDetailedView), "Copy", self)
        copyAction.setStatusTip("Copy to clipboard")
        copyAction.setToolTip("Copy to clipboard (Ctrl+C)")
        copyAction.triggered.connect(lambda: self.show_message("Copy", "Copied to clipboard"))
        toolbar.addAction(copyAction)
        
        # Paste action
        pasteAction = QAction(style.standardIcon(QStyle.SP_DialogYesButton), "Paste", self)
        pasteAction.setStatusTip("Paste from clipboard")
        pasteAction.setToolTip("Paste from clipboard (Ctrl+V)")
        pasteAction.triggered.connect(lambda: self.show_message("Paste", "Pasted from clipboard"))
        toolbar.addAction(pasteAction)
        
        toolbar.addSeparator()
        
        # Undo action
        undoAction = QAction(style.standardIcon(QStyle.SP_ArrowBack), "Undo", self)
        undoAction.setStatusTip("Undo last action")
        undoAction.setToolTip("Undo last action (Ctrl+Z)")
        undoAction.triggered.connect(lambda: self.show_message("Undo", "Undone last action"))
        toolbar.addAction(undoAction)
        
        # Redo action
        redoAction = QAction(style.standardIcon(QStyle.SP_ArrowForward), "Redo", self)
        redoAction.setStatusTip("Redo last action")
        redoAction.setToolTip("Redo last action (Ctrl+Y)")
        redoAction.triggered.connect(lambda: self.show_message("Redo", "Redone last action"))
        toolbar.addAction(redoAction)
        
        toolbar.addSeparator()
        
        # Search action
        searchAction = QAction(style.standardIcon(QStyle.SP_FileDialogContentsView), "Search", self)
        searchAction.setStatusTip("Search in document")
        searchAction.setToolTip("Search in document (Ctrl+F)")
        searchAction.triggered.connect(lambda: self.show_message("Search", "Search dialog would open here"))
        toolbar.addAction(searchAction)
        
        # Refresh action
        refreshAction = QAction(style.standardIcon(QStyle.SP_BrowserReload), "Refresh", self)
        refreshAction.setStatusTip("Refresh the view")
        refreshAction.setToolTip("Refresh the view (F5)")
        refreshAction.triggered.connect(lambda: self.show_message("Refresh", "View refreshed"))
        toolbar.addAction(refreshAction)
        
        toolbar.addSeparator()
        
        # Home action
        homeAction = QAction(style.standardIcon(QStyle.SP_DirHomeIcon), "Home", self)
        homeAction.setStatusTip("Go to home")
        homeAction.setToolTip("Go to home")
        homeAction.triggered.connect(lambda: self.show_message("Home", "Welcome home!"))
        toolbar.addAction(homeAction)
        
        # Info action
        infoAction = QAction(style.standardIcon(QStyle.SP_MessageBoxInformation), "Info", self)
        infoAction.setStatusTip("Show information")
        infoAction.setToolTip("Show information")
        infoAction.triggered.connect(self.show_about)
        toolbar.addAction(infoAction)
        
        # Help action
        helpAction = QAction(style.standardIcon(QStyle.SP_DialogHelpButton), "Help", self)
        helpAction.setStatusTip("Show help")
        helpAction.setToolTip("Show help (F1)")
        helpAction.triggered.connect(lambda: self.show_message("Help", "Help documentation would open here"))
        toolbar.addAction(helpAction)
        
        # Add stretch to push remaining items to the right
        spacer = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        
        # Theme toggle as a toolbar action
        themeAction = QAction(style.standardIcon(QStyle.SP_ComputerIcon), "Theme", self)
        themeAction.setStatusTip("Toggle theme")
        themeAction.setToolTip("Toggle between system and dark theme")
        themeAction.triggered.connect(self.toggle_theme)
        toolbar.addAction(themeAction)
        
        return toolbar
        
    def show_message(self, title, message):
        """Show a simple message box"""
        QMessageBox.information(self, title, message)
    
    def open_file(self):
        """Open file dialog"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Open File", 
            "", 
            "All Files (*);;Text Files (*.txt);;Python Files (*.py)"
        )
        if file_path:
            self.show_message("File Opened", f"Opened: {file_path}")
    
    def toggle_fullscreen(self, checked):
        """Toggle fullscreen mode"""
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About",
            "PySide6 Frameless Window Demo\n\n"
            "A demonstration of PySide6 widgets with\n"
            "frameless window and integrated menu bar.\n\n"
            "Built with PySide6 and qframelesswindow"
        )
        
    def create_basic_widgets_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Buttons section
        buttons_group = QGroupBox("Buttons")
        buttons_layout = QHBoxLayout()
        
        btn1 = QPushButton("Button 1")
        btn2 = QPushButton("Button 2")
        btn3 = QPushButton("Disabled")
        btn3.setEnabled(False)
        
        buttons_layout.addWidget(btn1)
        buttons_layout.addWidget(btn2)
        buttons_layout.addWidget(btn3)
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)
        
        # Checkboxes and Radio buttons
        selection_group = QGroupBox("Selection Widgets")
        selection_layout = QHBoxLayout()
        
        # Checkboxes
        check_layout = QVBoxLayout()
        check1 = QCheckBox("Option 1")
        check2 = QCheckBox("Option 2")
        check3 = QCheckBox("Option 3")
        check1.setChecked(True)
        check_layout.addWidget(check1)
        check_layout.addWidget(check2)
        check_layout.addWidget(check3)
        
        # Radio buttons
        radio_layout = QVBoxLayout()
        radio1 = QRadioButton("Choice A")
        radio2 = QRadioButton("Choice B")
        radio3 = QRadioButton("Choice C")
        radio1.setChecked(True)
        radio_layout.addWidget(radio1)
        radio_layout.addWidget(radio2)
        radio_layout.addWidget(radio3)
        
        selection_layout.addLayout(check_layout)
        selection_layout.addLayout(radio_layout)
        selection_group.setLayout(selection_layout)
        layout.addWidget(selection_group)
        
        # Progress bar with timer
        progress_group = QGroupBox("Progress Bar")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        self.progress_btn = QPushButton("Start Progress")
        self.progress_btn.clicked.connect(self.start_progress)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_btn)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "Basic Widgets")
        
    def create_input_widgets_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Text input
        text_group = QGroupBox("Text Input")
        text_layout = QVBoxLayout()
        
        line_edit = QLineEdit()
        line_edit.setPlaceholderText("Enter text here...")
        text_layout.addWidget(QLabel("Single Line Input:"))
        text_layout.addWidget(line_edit)
        
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Enter multiple lines of text...")
        text_edit.setMaximumHeight(100)
        text_layout.addWidget(QLabel("Multi-line Input:"))
        text_layout.addWidget(text_edit)
        
        text_group.setLayout(text_layout)
        layout.addWidget(text_group)
        
        # Numeric input
        numeric_group = QGroupBox("Numeric Input")
        numeric_layout = QHBoxLayout()
        
        # Spin box
        spin_layout = QVBoxLayout()
        spin_layout.addWidget(QLabel("Spin Box:"))
        spin_box = QSpinBox()
        spin_box.setRange(0, 100)
        spin_box.setValue(50)
        spin_layout.addWidget(spin_box)
        
        # Slider
        slider_layout = QVBoxLayout()
        slider_layout.addWidget(QLabel("Slider:"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        slider_label = QLabel("50")
        slider.valueChanged.connect(lambda v: slider_label.setText(str(v)))
        slider_layout.addWidget(slider)
        slider_layout.addWidget(slider_label)
        
        numeric_layout.addLayout(spin_layout)
        numeric_layout.addLayout(slider_layout)
        numeric_group.setLayout(numeric_layout)
        layout.addWidget(numeric_group)
        
        # Combo box
        combo_group = QGroupBox("Combo Box")
        combo_layout = QVBoxLayout()
        
        combo_box = QComboBox()
        combo_box.addItems(["Option 1", "Option 2", "Option 3", "Option 4", "Option 5"])
        combo_layout.addWidget(combo_box)
        
        combo_group.setLayout(combo_layout)
        layout.addWidget(combo_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "Input Widgets")
        
    def create_display_widgets_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # List widget
        list_group = QGroupBox("List Widget")
        list_layout = QVBoxLayout()
        
        list_widget = QListWidget()
        for i in range(10):
            list_widget.addItem(f"Item {i + 1}")
        list_widget.setMaximumHeight(150)
        
        list_layout.addWidget(list_widget)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        # Labels with different styles
        labels_group = QGroupBox("Labels")
        labels_layout = QVBoxLayout()
        
        normal_label = QLabel("Normal Label")
        labels_layout.addWidget(normal_label)
        
        bold_label = QLabel("Bold Label")
        bold_label.setFont(QFont("Arial", 10, QFont.Bold))
        labels_layout.addWidget(bold_label)
        
        colored_label = QLabel("Colored Label")
        colored_label.setStyleSheet("QLabel { color: #4CAF50; font-size: 14px; }")
        labels_layout.addWidget(colored_label)
        
        labels_group.setLayout(labels_layout)
        layout.addWidget(labels_group)
        
        layout.addStretch()
        self.tab_widget.addTab(tab, "Display Widgets")
        
    def toggle_theme(self):
        if self.is_dark_theme:
            self.apply_system_theme()
        else:
            self.apply_dark_theme()
        self.is_dark_theme = not self.is_dark_theme
        
    def apply_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.HighlightedText, Qt.black)
        QApplication.setPalette(dark_palette)
        
        # Apply dark theme to title bar, menu bar and search
        self.titleBar.setStyleSheet("""
            TitleBar {
                background-color: #353535;
            }
            TitleBar QLabel {
                color: white;
                background-color: transparent;
            }
            QMenuBar {
                background-color: transparent;
                color: white;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 8px;
            }
            QMenuBar::item:selected {
                background-color: #505050;
            }
            QMenuBar::item:pressed {
                background-color: #606060;
            }
            QLineEdit {
                background-color: #2d2d2d;
                border: 1px solid #454545;
                color: white;
                selection-background-color: #0078d4;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
                background-color: #1e1e1e;
            }
            QLineEdit::placeholder {
                color: #999999;
            }
        """)
        
        # Apply dark theme to toolbar
        self.toolbar.setStyleSheet("""
            QToolBar {
                background-color: #404040;
                border: none;
                padding: 5px;
            }
            QToolBar::separator {
                background-color: #606060;
                width: 1px;
                margin: 5px;
            }
            QToolButton {
                background-color: transparent;
                border: none;
                padding: 5px;
                color: white;
            }
            QToolButton:hover {
                background-color: #505050;
                border-radius: 4px;
            }
            QToolButton:pressed {
                background-color: #606060;
                border-radius: 4px;
            }
        """)
        
        # Set title bar button colors for dark theme
        if hasattr(self.titleBar, 'minBtn'):
            self.titleBar.minBtn.setNormalColor(Qt.white)
            self.titleBar.minBtn.setHoverColor(Qt.white)
            self.titleBar.minBtn.setPressedColor(Qt.white)
            self.titleBar.minBtn.setHoverBackgroundColor(QColor(80, 80, 80))
            
        if hasattr(self.titleBar, 'maxBtn'):
            self.titleBar.maxBtn.setNormalColor(Qt.white)
            self.titleBar.maxBtn.setHoverColor(Qt.white)
            self.titleBar.maxBtn.setPressedColor(Qt.white)
            self.titleBar.maxBtn.setHoverBackgroundColor(QColor(80, 80, 80))
            
        if hasattr(self.titleBar, 'closeBtn'):
            # Keep close button red on hover but make icon white
            self.titleBar.closeBtn.setNormalColor(Qt.white)
        
    def is_system_dark_theme(self):
        """Check if the system is using a dark theme"""
        # Get the system palette
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
    
    def apply_system_theme(self):
        """Apply the system theme and set appropriate icon colors"""
        QApplication.setPalette(QApplication.style().standardPalette())
        
        # Check if system is using dark theme
        is_dark = self.is_system_dark_theme()
        
        if is_dark:
            # Apply dark system theme styling to menu bar and search
            self.titleBar.setStyleSheet("""
                QMenuBar {
                    background-color: transparent;
                    color: white;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 4px 8px;
                }
                QMenuBar::item:selected {
                    background-color: rgba(255, 255, 255, 30);
                }
                QMenuBar::item:pressed {
                    background-color: rgba(255, 255, 255, 40);
                }
                QLineEdit {
                    background-color: #2d2d2d;
                    border: 1px solid #454545;
                    color: white;
                    selection-background-color: #0078d4;
                }
                QLineEdit:focus {
                    border: 1px solid #0078d4;
                    background-color: #1e1e1e;
                }
                QLineEdit::placeholder {
                    color: #999999;
                }
            """)
            # Apply dark system theme to toolbar
            self.toolbar.setStyleSheet("""
                QToolBar {
                    background-color: #404040;
                    border: none;
                    padding: 5px;
                }
                QToolBar::separator {
                    background-color: #606060;
                    width: 1px;
                    margin: 5px;
                }
                QToolButton {
                    background-color: transparent;
                    border: none;
                    padding: 5px;
                    color: white;
                }
                QToolButton:hover {
                    background-color: #505050;
                    border-radius: 4px;
                }
                QToolButton:pressed {
                    background-color: #606060;
                    border-radius: 4px;
                }
            """)
            # System has dark theme - use white icons
            icon_color = Qt.white
            hover_bg = QColor(80, 80, 80)
        else:
            # Apply light theme styling for search bar
            self.titleBar.setStyleSheet("""
                QLineEdit {
                    background-color: white;
                    border: 1px solid #d0d0d0;
                    color: black;
                    selection-background-color: #0078d4;
                }
                QLineEdit:focus {
                    border: 1px solid #0078d4;
                }
                QLineEdit::placeholder {
                    color: #666666;
                }
            """)
            # Reset toolbar style to default for light theme
            self.toolbar.setStyleSheet("")
            # System has light theme - use black icons
            icon_color = Qt.black
            hover_bg = QColor(0, 0, 0, 26)
        
        # Set title bar button colors based on system theme
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
            self.titleBar.closeBtn.setNormalColor(icon_color)
        
    def start_progress(self):
        self.progress_value = 0
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(50)
        self.progress_btn.setEnabled(False)
        
    def update_progress(self):
        self.progress_value += 2
        self.progress_bar.setValue(self.progress_value)
        
        if self.progress_value >= 100:
            self.progress_timer.stop()
            self.progress_btn.setEnabled(True)
            self.progress_bar.setValue(0)
            
    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Resize container to fill the window below the title bar
        self.container.setGeometry(0, self.titleBar.height(), self.width(), self.height() - self.titleBar.height())
        # Ensure title bar is properly positioned
        self.titleBar.raise_()


def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Create and show the demo window
    window = DemoWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()