"""Icon cache module for WaveScout.

This module provides centralized icon generation and caching for the application.
It generates distinct icons for different scope types and signals, with colors
optimized for visibility in both light and dark themes.
"""

from typing import Dict, Optional, Literal, Union
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

ScopeType = Literal[
    "module", "task", "function", "begin", "fork", "generate", "struct", "union",
    "class", "interface", "package", "program", "vhdl_architecture", "vhdl_procedure",
    "vhdl_function", "vhdl_record", "vhdl_process", "vhdl_block", "vhdl_for_generate",
    "vhdl_if_generate", "vhdl_generate", "vhdl_package", "ghw_generic", "vhdl_array",
    "unknown"
]


class IconCache:
    """Singleton class for managing and caching application icons."""
    
    _instance: Optional['IconCache'] = None
    _initialized: bool = False
    
    def __new__(cls) -> 'IconCache':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        if not self._initialized:
            self._scope_icons: Dict[str, QIcon] = {}
            self._signal_icon: Optional[QIcon] = None
            self._generate_all_icons()
            self.__class__._initialized = True
    
    def _generate_all_icons(self) -> None:
        """Generate all icons on initialization."""
        app = QApplication.instance()
        if not app:
            return
        
        try:
            self._generate_signal_icon()
            self._generate_scope_icons()
        except Exception as e:
            print(f"Failed to generate icons: {e}")
    
    def _generate_signal_icon(self) -> None:
        """Generate the signal icon (waveform-like)."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Use a vibrant blue that works on both themes
        signal_color = QColor("#00A8E8")  # Bright cyan-blue
        
        # Fill with semi-transparent background
        brush = QBrush(QColor(signal_color))
        brush.setStyle(Qt.BrushStyle.SolidPattern)
        brush.setColor(QColor(signal_color.red(), signal_color.green(), signal_color.blue(), 40))
        painter.setBrush(brush)
        
        pen = QPen(signal_color)
        pen.setWidth(2)
        painter.setPen(pen)
        
        # Draw filled digital waveform shape
        points = [
            (2, 12), (4, 12), (4, 4), (8, 4),
            (8, 12), (12, 12), (12, 4), (14, 4),
            (14, 6), (12, 6), (12, 10), (8, 10),
            (8, 6), (4, 6), (4, 10), (2, 10)
        ]
        
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF
        polygon = QPolygonF([QPointF(x, y) for x, y in points])
        painter.drawPolygon(polygon)
        
        painter.end()
        self._signal_icon = QIcon(pixmap)
    
    def _generate_scope_icons(self) -> None:
        """Generate distinct icons for each scope type."""
        
        # Color scheme optimized for both light and dark themes
        # Using saturated colors with good contrast
        colors: Dict[str, Union[str, Dict[str, str]]] = {
            # Verilog/SystemVerilog scopes
            "module": {"border": "#FF6B35", "fill": "#FF8C5A"},         # Vibrant orange
            "interface": "#00BFB3",      # Teal
            "package": "#A855F7",         # Purple
            "program": "#3B82F6",         # Blue
            "class": "#10B981",           # Emerald green
            
            # Procedural blocks
            "task": "#FBBF24",            # Amber
            "function": "#F97316",        # Orange
            "begin": "#6B7280",           # Gray
            "fork": "#8B5CF6",            # Violet
            
            # Generate blocks
            "generate": "#14B8A6",        # Cyan
            
            # Structs/unions
            "struct": "#EC4899",          # Pink
            "union": "#F43F5E",           # Rose
            
            # VHDL scopes
            "vhdl_architecture": "#EF4444",  # Red
            "vhdl_procedure": "#EAB308",     # Yellow
            "vhdl_function": "#FB923C",      # Orange
            "vhdl_record": "#C084FC",        # Purple
            "vhdl_process": "#60A5FA",       # Sky blue
            "vhdl_block": "#9CA3AF",         # Gray
            "vhdl_for_generate": "#2DD4BF",  # Teal
            "vhdl_if_generate": "#34D399",   # Emerald
            "vhdl_generate": "#14B8A6",      # Cyan
            "vhdl_package": "#A78BFA",       # Violet
            "vhdl_array": "#818CF8",         # Indigo
            
            # Special
            "ghw_generic": "#94A3B8",        # Slate
            "unknown": "#D1D5DB",            # Light gray
        }
        
        for scope_type, color in colors.items():
            if isinstance(color, dict):
                self._scope_icons[scope_type] = self._create_scope_icon(scope_type, color["border"], color.get("fill", color["border"]))
            else:
                self._scope_icons[scope_type] = self._create_scope_icon(scope_type, color, color)
    
    def _create_scope_icon(self, scope_type: str, border_color: str, fill_color: str) -> QIcon:
        """Create a specific icon for a scope type with fill."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Setup colors
        border = QColor(border_color)
        fill = QColor(fill_color)
        fill.setAlpha(60)  # Semi-transparent fill
        
        pen = QPen(border)
        pen.setWidth(1)
        painter.setPen(pen)
        
        brush = QBrush(fill)
        painter.setBrush(brush)
        
        # Different shapes for different scope types
        if scope_type in ["module", "vhdl_architecture"]:
            # Box with rounded corners and ports
            painter.drawRoundedRect(3, 4, 10, 8, 2, 2)
            # Add port indicators
            painter.setBrush(QBrush(border))
            painter.drawRect(1, 5, 2, 2)
            painter.drawRect(13, 5, 2, 2)
            painter.drawRect(1, 9, 2, 2)
            painter.drawRect(13, 9, 2, 2)
            
        elif scope_type in ["interface"]:
            # Double-bordered box with connection points
            painter.drawRect(4, 5, 8, 6)
            painter.drawRect(3, 4, 10, 8)
            # Connection points
            painter.setBrush(QBrush(border))
            painter.drawEllipse(1, 7, 3, 3)
            painter.drawEllipse(12, 7, 3, 3)
            
        elif scope_type in ["class"]:
            # UML-style class box
            painter.drawRect(3, 3, 10, 10)
            painter.drawLine(3, 6, 13, 6)
            painter.drawLine(3, 9, 13, 9)
            
        elif scope_type in ["package", "vhdl_package"]:
            # Package icon - box with tab
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(3, 5)
            path.lineTo(3, 12)
            path.lineTo(13, 12)
            path.lineTo(13, 5)
            path.lineTo(9, 5)
            path.lineTo(9, 3)
            path.lineTo(3, 3)
            path.lineTo(3, 5)
            painter.fillPath(path, brush)
            painter.drawPath(path)
            
        elif scope_type in ["task", "vhdl_procedure"]:
            # Task shape - box with T
            painter.drawRoundedRect(3, 4, 10, 8, 1, 1)
            painter.setFont(painter.font())
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawText(6, 10, "T")
            
        elif scope_type in ["function", "vhdl_function"]:
            # Function shape - box with f
            painter.drawRoundedRect(3, 4, 10, 8, 1, 1)
            painter.setFont(painter.font())
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawText(6, 10, "ƒ")
            
        elif scope_type in ["begin", "vhdl_block"]:
            # Bracket shape for begin/end blocks
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(5, 3)
            path.lineTo(3, 3)
            path.lineTo(3, 13)
            path.lineTo(5, 13)
            path.moveTo(11, 3)
            path.lineTo(13, 3)
            path.lineTo(13, 13)
            path.lineTo(11, 13)
            painter.fillPath(path, brush)
            painter.drawPath(path)
            
        elif scope_type == "fork":
            # Fork shape - branching lines
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(8, 3)
            path.lineTo(8, 8)
            path.moveTo(8, 8)
            path.lineTo(4, 13)
            path.moveTo(8, 8)
            path.lineTo(12, 13)
            painter.setPen(pen)
            painter.drawPath(path)
            # Add junction point
            painter.setBrush(QBrush(border))
            painter.drawEllipse(6, 6, 4, 4)
            
        elif scope_type in ["generate", "vhdl_generate", "vhdl_for_generate", "vhdl_if_generate"]:
            # Loop/generate symbol with arrow
            painter.drawEllipse(3, 4, 10, 8)
            # Arrow indicating iteration
            from PySide6.QtGui import QPainterPath
            arrow = QPainterPath()
            arrow.moveTo(8, 2)
            arrow.lineTo(6, 4)
            arrow.lineTo(8, 4)
            arrow.lineTo(10, 4)
            arrow.lineTo(8, 2)
            painter.fillPath(arrow, QBrush(border))
            
        elif scope_type in ["struct", "vhdl_record"]:
            # Stacked rectangles for struct
            painter.drawRect(3, 3, 10, 3)
            painter.drawRect(3, 7, 10, 3)
            painter.drawRect(3, 11, 10, 3)
            
        elif scope_type in ["union"]:
            # Overlapping rectangles for union
            painter.setOpacity(0.7)
            painter.drawRect(2, 4, 8, 8)
            painter.drawRect(6, 4, 8, 8)
            painter.setOpacity(1.0)
            
        elif scope_type in ["program", "vhdl_process"]:
            # Diamond shape for program/process blocks
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            points = [
                QPointF(8, 2),
                QPointF(14, 8),
                QPointF(8, 14),
                QPointF(2, 8)
            ]
            polygon = QPolygonF(points)
            painter.drawPolygon(polygon)
        
        elif scope_type == "vhdl_array":
            # Grid pattern for arrays
            for i in range(3):
                for j in range(3):
                    painter.drawRect(3 + i*4, 3 + j*4, 3, 3)
                    
        elif scope_type == "ghw_generic":
            # Generic shape - hexagon
            from PySide6.QtGui import QPolygonF
            from PySide6.QtCore import QPointF
            points = [
                QPointF(5, 3),
                QPointF(11, 3),
                QPointF(14, 8),
                QPointF(11, 13),
                QPointF(5, 13),
                QPointF(2, 8)
            ]
            polygon = QPolygonF(points)
            painter.drawPolygon(polygon)
                
        else:  # "unknown" and fallback
            # Simple folder shape as fallback
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(2, 5)
            path.lineTo(2, 13)
            path.lineTo(14, 13)
            path.lineTo(14, 5)
            path.lineTo(10, 5)
            path.lineTo(10, 3)
            path.lineTo(6, 3)
            path.lineTo(4, 5)
            path.lineTo(2, 5)
            painter.fillPath(path, brush)
            painter.drawPath(path)
        
        painter.end()
        return QIcon(pixmap)
    
    def get_signal_icon(self) -> Optional[QIcon]:
        """Get the cached signal icon."""
        return self._signal_icon
    
    def get_scope_icon(self, scope_type: str = "unknown") -> Optional[QIcon]:
        """Get the cached icon for a specific scope type.
        
        Args:
            scope_type: The type of scope (module, interface, etc.)
            
        Returns:
            The QIcon for the scope type, or the 'unknown' icon if type not found
        """
        if scope_type in self._scope_icons:
            return self._scope_icons[scope_type]
        return self._scope_icons.get("unknown")


def get_icon_cache() -> IconCache:
    """Get the singleton IconCache instance."""
    return IconCache()