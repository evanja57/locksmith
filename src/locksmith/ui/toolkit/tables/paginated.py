# -*- encoding: utf-8 -*-
"""
locksmith.ui.toolkit.tables.paginated module

Main paginated table widget with search, sort, and pagination.
"""
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtGui import QIcon, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
    QSizePolicy,
    QLabel,
    QFrame, QHBoxLayout,
)
from keri import help

from locksmith.ui import colors
from locksmith.ui.styles import get_monospace_font_family
from locksmith.ui.toolkit.tables.components import (
    TableHeader,
    PaginationControls,
    SkewersMenuButton,
)
from locksmith.ui.toolkit.widgets import LocksmithButton

logger = help.ogler.getLogger(__name__)

# Get assets directory path relative to this module
_ASSETS_DIR = Path(__file__).resolve().parents[5] / "assets" / "material-icons"


class SortOrder(Enum):
    """Sort order enumeration."""
    ASCENDING = "asc"
    DESCENDING = "desc"


class PaginatedTableWidget(QWidget):
    """
    Reusable searchable, sortable, paginated table widget.

    Supports flexible data loading via a loader function that handles
    both database and API data sources transparently.

    Features:
    - Customizable header with icon, title, search, and add button
    - Sortable columns (click headers to sort)
    - Pagination controls
    - Row action menus (skewer menus)
    - Individual cell text color customization
    - Horizontal dynamic sizing
    """

    # Signals
    search_changed = Signal(str)  # search_term
    page_changed = Signal(int)  # new_page_number
    sort_changed = Signal(int, str)  # column_index, sort_order
    add_clicked = Signal()
    row_action_triggered = Signal(object, str)  # row_data, action_name
    row_clicked = Signal(object)  # row_data
    load_requested = Signal(dict)  # {"page": int, "page_size": int, "filter_term": str|None, "order": list|None}
    load_error = Signal(str)  # error_message

    def __init__(
            self,
            columns: List[str],
            column_widths: Optional[Dict[str, int]] = None,
            title: str = "",
            icon_path: Optional[str] = None,
            loader_func: Optional[Callable] = None,
            items_per_page: int = 25,
            show_search: bool = True,
            show_add_button: bool = True,
            add_button_text: str = "Add",
            row_actions: Optional[List[str]] = None,
            row_action_icons: Optional[Dict[str, str]] = None,
            row_actions_callback: Optional[Callable[[Dict[str, Any]], tuple[List[str], Dict[str, str]]]] = None,
            column_sort_mapping: Optional[Dict[str, str]] = None,
            transform_func: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
            monospace_columns: Optional[List[str]] = None,
            filter_func: Optional[Callable] = None,
            parent=None,
            *,
            separate_toolbar: bool = False
    ):
        """
        Initialize the PaginatedTableWidget.

        Args:
            columns: List of column names (last column will be "Actions" if row_actions provided)
            column_widths: Optional dict mapping column names to fixed widths
            title: Header title text
            icon_path: Optional path to icon for header
            loader_func: Optional function to load data (sync). Signature:
                         (page: int, search: str, sort_col: int, sort_order: str) -> (List[Dict], int)
                         Returns (data_list, total_items)
            items_per_page: Number of items per page
            show_search: Whether to show search bar
            show_add_button: Whether to show add button
            add_button_text: Text for add button
            row_actions: Optional list of action names for row menus
            row_action_icons: Optional dict mapping action names to full icon paths
            row_actions_callback: Optional callback to determine actions per row. Signature:
                                  (row_data: Dict[str, Any]) -> (actions: List[str], icons: Dict[str, str])
                                  If provided, overrides static row_actions and row_action_icons per row
            column_sort_mapping: Optional dict mapping column names to API field names for sorting
                                 (e.g., {"Alias": "alias", "AID": "aid"})
            transform_func: Optional function to transform API response items to row dicts.
                            Signature: (api_item: Dict) -> Dict[str, Any]
            monospace_columns: Optional list of column names that should use monospace font.
                               Defaults to common identifier columns.
            filter_func: Optional callback function to invoke when filter button is clicked.
                        When provided, a filter button appears to the left of the search box.
            parent: Parent widget
            separate_toolbar: Put header search and actions on a row below the title
        """
        super().__init__(parent)

        self.columns = columns
        self.loader_func = loader_func or self._default_static_loader
        self.items_per_page = items_per_page
        self.row_actions = row_actions or []
        self.row_action_icons = row_action_icons or {}
        self.row_actions_callback = row_actions_callback
        self.column_widths = column_widths or {}
        self.title = title
        self.icon_path = icon_path
        self.add_button_text = add_button_text
        self.column_sort_mapping = column_sort_mapping or {}
        self.transform_func = transform_func
        self.monospace_columns = monospace_columns if monospace_columns is not None else [
            "AID", "Prefix", "Identifier", "Pre", "Witness AID", 
            "Controller", "Signing Identifier", "Destination Identifier"
        ]

        # Async loading mode flag
        self._use_async_loading = bool(column_sort_mapping is not None or transform_func is not None)

        # State
        self.current_page = 1
        self.total_items = 0
        self.total_pages = 1
        self.current_search = ""
        self.current_filter = {}
        self.current_sort_column = -1  # -1 means no sort
        self.current_sort_order = SortOrder.ASCENDING
        self.show_add_button = show_add_button

        # Static data (for default loader)
        self._static_data: List[Dict[str, Any]] = []
        self._current_page_data: List[Dict[str, Any]] = []

        # Determine if we need an Actions column
        self.has_actions_column = len(self.row_actions) > 0
        if self.has_actions_column and columns[-1] != "Actions":
            self.columns = columns + ["Actions"]

        # Set size policy to expand
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Create main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(0)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Create header
        self.header = TableHeader(
            icon_path=icon_path,
            title=title,
            show_search=show_search,
            show_add_button=show_add_button,
            add_button_text=add_button_text,
            filter_func=filter_func,
            separate_toolbar=separate_toolbar
        )
        self.header.search_changed.connect(self._on_search_changed)
        self.header.add_clicked.connect(self.add_clicked.emit)
        main_layout.addWidget(self.header)

        # Create table
        self.table = QTableWidget()
        self._setup_table()
        main_layout.addWidget(self.table)

        # Create empty state widget (initially hidden)
        self.empty_state = self._create_empty_state()
        self.empty_state.setVisible(False)
        main_layout.addWidget(self.empty_state)

        # Create loading state widget (initially hidden)
        self.loading_state = self._create_loading_state()
        self.loading_state.setVisible(False)
        main_layout.addWidget(self.loading_state)

        # Create pagination controls
        self.pagination = PaginationControls()
        self.pagination.page_changed.connect(self._on_page_changed)
        main_layout.addWidget(self.pagination)

        # Push everything to the top
        main_layout.addStretch()

        logger.info(f"PaginatedTableWidget initialized: title='{title}', columns={len(self.columns)}")

    def showEvent(self, event):
        super().showEvent(event)
        # Opening a list should not start text entry. Tab still reaches search.
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _setup_table(self):
        """Setup table widget configuration and styling."""
        # Set column count
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)

        # Set alignment for individual header items
        # First, set all headers to left-aligned
        for col in range(len(self.columns)):
            header_item = self.table.horizontalHeaderItem(col)
            if header_item:
                if self.has_actions_column and col == len(self.columns) - 1:
                    # Actions column header: right-aligned
                    header_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    # All other columns: left-aligned
                    header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Table behavior
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setTabKeyNavigation(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # Read-only
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)  # Hide row numbers
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(50)

        # Disable automatic sorting; we handle it manually in _on_header_clicked
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        # Enable hover highlighting
        self.table.setMouseTracking(True)
        self.table.cellEntered.connect(self.table.selectRow)
        self.table.viewport().installEventFilter(self)
        self.table.cellPressed.connect(self._on_cell_clicked)


        # Header configuration
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Stretch all content columns proportionally
        for col in range(len(self.columns)):
            if self.has_actions_column and col == len(self.columns) - 1:
                # Actions column: fixed width
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
                self.table.setColumnWidth(col, 100)
            if self.columns[col] in self.column_widths:
                self.table.setColumnWidth(col, self.column_widths[self.columns[col]])
            else:
                # Content columns: stretch
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        # Table styling
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {colors.BACKGROUND_CONTENT};
                border-left: 1px solid {colors.BORDER_TABLE};
                border-right: 1px solid {colors.BORDER_TABLE};
                border-bottom: none;
                border-top: 1px solid {colors.BORDER_TABLE};
                gridline-color: {colors.BACKGROUND_NEUTRAL};
                selection-background-color: {colors.BACKGROUND_NEUTRAL};
            }}
            QTableWidget::item {{
                padding-left: 12px;
                border-bottom: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-left: none;
                border-right: none;
                border-top: none;
            }}
            QTableWidget::item:selected {{
                background-color: {colors.BACKGROUND_TABLE_HEADER};
                color: {colors.TEXT_PRIMARY};
            }}
        """)
        # Header styling with dynamic asset paths
        chevron_down_path = _ASSETS_DIR / "chevron_down.svg"
        chevron_up_path = _ASSETS_DIR / "chevron_up.svg"

        self.table.horizontalHeader().setStyleSheet(f"""
            QHeaderView::section {{
                background-color: {colors.BACKGROUND_TABLE_ROW_HOVER};
                padding: 12px;
                border: none;
                border-bottom: 1px solid {colors.BACKGROUND_NEUTRAL};
                font-size: 14px;
                font-weight: 600;
                color: {colors.TEXT_PRIMARY};
                text-align: left;
            }}
            QHeaderView::section:hover {{
                background-color: {colors.BACKGROUND_TABLE_ROW_SELECTED};
            }}
            QHeaderView::section:focus {{
                background-color: {colors.BACKGROUND_TABLE_ROW_PRESSED};
            }}
            QHeaderView::down-arrow {{
                image: url({chevron_down_path});
                width: 20px;
                height: 20px;
            }}
            QHeaderView::up-arrow {{
                image: url({chevron_up_path});
                width: 20px;
                height: 20px;
            }}
        """)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Set pointer cursor for clickable rows and headers
        self.table.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.table.horizontalHeader().viewport().setCursor(Qt.CursorShape.PointingHandCursor)

    def _create_empty_state(self) -> QWidget:
        """
        Create the empty state widget to display when there's no data.

        Returns:
            Widget containing the empty state UI
        """

        # Main container with grey border
        container = QFrame()
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.BACKGROUND_CONTENT};
                border-left: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-right: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-bottom: 1px solid {colors.BACKGROUND_NEUTRAL};
            }}
        """)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Calculate height for 10 rows (same as one page)
        row_height = 50  # Same as table row height
        total_height = row_height * self.items_per_page
        container.setFixedHeight(total_height)

        # Container layout
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.setContentsMargins(20, 20, 20, 20)

        # Inner rounded box
        inner_box = QFrame()
        inner_box.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.BACKGROUND_CONTENT};
                border: 2px solid {colors.BACKGROUND_NEUTRAL};
                border-radius: 4px;
            }}
        """)
        inner_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        inner_box.setFixedWidth(550)
        inner_box.setFixedHeight(320)
        # VBox layout for content
        vbox = QVBoxLayout(inner_box)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.setContentsMargins(40, 40, 40, 40)
        vbox.setSpacing(40)

        # Header icon
        header_row = QHBoxLayout()
        header_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.setSpacing(20)
        if self.icon_path:
            icon = QIcon(self.icon_path)
            if not icon.isNull():
                icon_label = QLabel()
                icon_label.setStyleSheet("""
                        QLabel {
                            border: none;
                            background-color: transparent;
                        }
                    """)
                pixmap = icon.pixmap(48, 48)
                icon_label.setPixmap(pixmap)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                header_row.addWidget(icon_label)

        # Title text
        title_label = QLabel(f"NO {self.title.upper()}")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-size: 24px;
                font-weight: 600;
                border: none;
                color: {colors.TEXT_PRIMARY};
            }}
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(title_label)

        vbox.addLayout(header_row)

        # Add button
        if self.show_add_button:
            add_button = LocksmithButton(self.add_button_text, icon_path=self.icon_path)
            add_button.clicked.connect(self.add_clicked.emit)
            add_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            add_button.setFixedWidth(360)
            vbox.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignCenter)

        container_layout.addWidget(inner_box, alignment=Qt.AlignmentFlag.AlignCenter)

        return container

    def _create_loading_state(self) -> QWidget:
        """
        Create the loading state widget to display while data is being fetched.

        Returns:
            Widget containing the loading state UI
        """
        # Main container with grey border (same as empty state)
        container = QFrame()
        container.setFrameShape(QFrame.Shape.NoFrame)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.BACKGROUND_CONTENT};
                border-left: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-right: 1px solid {colors.BACKGROUND_NEUTRAL};
                border-bottom: 1px solid {colors.BACKGROUND_NEUTRAL};
            }}
        """)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Calculate height for page rows
        row_height = 50
        total_height = row_height * self.items_per_page
        container.setFixedHeight(total_height)

        # Container layout
        container_layout = QVBoxLayout(container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.setContentsMargins(20, 20, 20, 20)

        # Inner rounded box
        inner_box = QFrame()
        inner_box.setStyleSheet(f"""
            QFrame {{
                background-color: {colors.BACKGROUND_CONTENT};
                border: 2px solid {colors.BACKGROUND_NEUTRAL};
                border-radius: 4px;
            }}
        """)
        inner_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        inner_box.setFixedWidth(400)
        inner_box.setFixedHeight(180)

        # VBox layout for content
        vbox = QVBoxLayout(inner_box)
        vbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox.setContentsMargins(40, 40, 40, 40)
        vbox.setSpacing(20)

        # Header row with icon
        header_row = QHBoxLayout()
        header_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.setSpacing(20)

        if self.icon_path:
            icon = QIcon(self.icon_path)
            if not icon.isNull():
                icon_label = QLabel()
                icon_label.setStyleSheet("""
                    QLabel {
                        border: none;
                        background-color: transparent;
                    }
                """)
                pixmap = icon.pixmap(48, 48)
                icon_label.setPixmap(pixmap)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                header_row.addWidget(icon_label)

        # Loading text
        loading_label = QLabel("Loading...")
        loading_label.setStyleSheet(f"""
            QLabel {{
                font-size: 24px;
                font-weight: 600;
                border: none;
                color: {colors.TEXT_PRIMARY};
            }}
        """)
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_row.addWidget(loading_label)

        vbox.addLayout(header_row)

        container_layout.addWidget(inner_box, alignment=Qt.AlignmentFlag.AlignCenter)

        return container

    def show_loading(self):
        """
        Show loading state. Call this before starting async data fetch.
        
        The loading state will automatically hide when set_static_data() 
        or _display_data() is called.
        """
        self._display_loading_state()

    def _display_loading_state(self):
        """Display loading state while data is being fetched."""
        # Hide table rows, pagination, and empty state
        self.table.setVisible(True)  # Keep header visible
        self.table.setRowCount(0)  # Clear any rows
        self._resize_table_to_content()  # Resize to just show header

        self.pagination.setVisible(False)
        self.empty_state.setVisible(False)

        # Show loading state
        self.loading_state.setVisible(True)

        logger.debug("Displaying loading state")

    def request_load(self):
        """
        Request data load by emitting load_requested signal.

        Use this for async API loading. The parent should connect to
        load_requested, perform the async fetch, and call set_page_data().
        """
        self._display_loading_state()

        # Build order list from current sort state
        order = self._build_sort_order()

        # Emit signal with 0-indexed page
        self.load_requested.emit({
            "page": self.current_page - 1,  # Convert to 0-indexed
            "page_size": self.items_per_page,
            "filter_term": self.current_search if self.current_search else None,
            "order": order
        })

        logger.debug(
            f"Load requested: page={self.current_page - 1}, "
            f"filter={self.current_search}, order={order}"
        )

    def set_page_data(self, response: Dict[str, Any], data_key: str = "identifiers"):
        """
        Set page data from an API response.

        Use this method for async API loading. Call this after receiving
        the API response.

        Args:
            response: API response dict with format:
                      {'page': 0, 'num_pages': 2, 'count': 11, '<data_key>': [...]}
                      Or on error: {'success': False, 'error': '...'}
            data_key: Key in response containing the data list (default: "identifiers")
        """
        # Check for error response
        if response.get("success") is False:
            error_msg = response.get("error", "Unknown error")
            logger.error(f"API load error: {error_msg}")
            self.load_error.emit(error_msg)
            self._display_error()
            return

        try:
            # Extract pagination info
            api_page = response.get("page", 0)
            self.total_pages = response.get("num_pages", 1)
            self.total_items = response.get("count", 0)
            self.current_page = api_page + 1  # Convert to 1-indexed

            # Extract data
            raw_data = response.get(data_key, [])

            # Transform data if transform function provided
            if self.transform_func:
                page_data = [self.transform_func(item) for item in raw_data]
            else:
                page_data = raw_data

            # Check if we have data
            if self.total_items == 0:
                self._display_empty_state()
            else:
                self._display_data(page_data)
                self.pagination.set_pagination(
                    self.current_page,
                    self.total_pages,
                    self.total_items
                )

            logger.debug(
                f"Page data set: page={self.current_page}/{self.total_pages}, "
                f"items={len(page_data)}, total={self.total_items}"
            )

        except Exception as e:
            logger.error(f"Error processing API response: {e}", exc_info=True)
            self.load_error.emit(str(e))
            self._display_error()

    def _build_sort_order(self) -> Optional[List[str]]:
        """
        Build API sort order list from current sort state.

        Returns:
            List like ['+alias', '-aid'] or None if no sort
        """
        if self.current_sort_column < 0:
            return None

        if self.current_sort_column >= len(self.columns):
            return None

        column_name = self.columns[self.current_sort_column]

        # Skip if this is the Actions column
        if self.has_actions_column and self.current_sort_column == len(self.columns) - 1:
            return None

        # Map column name to API field name
        api_field = self.column_sort_mapping.get(column_name, column_name.lower())

        # Build sort string with +/- prefix
        prefix = "+" if self.current_sort_order == SortOrder.ASCENDING else "-"

        return [f"{prefix}{api_field}"]

    def set_static_data(self, data: List[Dict[str, Any]], *, reset_page: bool = True):
        """
        Set static data for client-side filtering, sorting, and pagination.

        Use this method for database or in-memory data that doesn't require
        API calls for filtering/sorting/pagination.

        Args:
            data: List of dictionaries representing rows
            reset_page: Return to page one, or keep the current page during a refresh.
        """
        self._static_data = data
        # Switch to the static loader for subsequent _load_data calls
        self.loader_func = self._default_static_loader
        if reset_page:
            self.current_page = 1
        self._load_data()
        logger.debug(f"Static data set: {len(data)} items")

    def _default_static_loader(
        self,
        page: int,
        search: str,
        sort_col: int,
        sort_order: str
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Default loader for static/client-side data.

        Performs filtering, sorting, and pagination on _static_data.

        Args:
            page: Page number (1-indexed)
            search: Search term
            sort_col: Column index to sort by (-1 for no sort)
            sort_order: 'asc' or 'desc'

        Returns:
            Tuple of (page_data, total_items)
        """
        # Filter data
        filtered_data = self._filter_data(self._static_data, search)

        # Sort data
        if sort_col >= 0 and sort_col < len(self.columns):
            sorted_data = self._sort_data(filtered_data, sort_col, sort_order)
        else:
            sorted_data = filtered_data

        # Paginate
        total_items = len(sorted_data)
        start_idx = (page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_data = sorted_data[start_idx:end_idx]

        return page_data, total_items

    def _filter_data(self, data: List[Dict[str, Any]], search: str) -> List[Dict[str, Any]]:
        """
        Filter data by search term (case-insensitive).

        Args:
            data: Data to filter
            search: Search term

        Returns:
            Filtered data
        """
        if not search:
            return data

        search_lower = search.lower()
        filtered = []

        for row in data:
            # Search in all string values
            for value in row.values():
                if isinstance(value, str) and search_lower in value.lower():
                    filtered.append(row)
                    break

        return filtered

    def _sort_data(
        self,
        data: List[Dict[str, Any]],
        sort_col: int,
        sort_order: str
    ) -> List[Dict[str, Any]]:
        """
        Sort data by column.

        Args:
            data: Data to sort
            sort_col: Column index
            sort_order: 'asc' or 'desc'

        Returns:
            Sorted data
        """
        if sort_col < 0 or sort_col >= len(self.columns):
            return data

        column_name = self.columns[sort_col]

        # Skip sorting if this is the Actions column
        if self.has_actions_column and sort_col == len(self.columns) - 1:
            return data

        reverse = (sort_order == SortOrder.DESCENDING.value)

        try:
            sorted_data = sorted(
                data,
                key=lambda x: x.get(column_name, ""),
                reverse=reverse
            )
            return sorted_data
        except Exception as e:
            logger.warning(f"Error sorting data: {e}")
            return data

    def _load_data(self):
        """Load data using the loader function and update the table."""
        try:
            # Call loader function
            page_data, total_items = self.loader_func(
                self.current_page,
                self.current_search,
                self.current_sort_column,
                self.current_sort_order.value
            )

            # Update state
            self.total_items = total_items
            self.total_pages = max(1, (total_items + self.items_per_page - 1) // self.items_per_page)

            # Ensure current page is valid
            if self.current_page > self.total_pages:
                self.current_page = max(1, self.total_pages)
                # Reload with corrected page
                return self._load_data()

            # Check if we have data
            if total_items == 0:
                # Show empty state
                self._display_empty_state()
            else:
                # Update table
                self._display_data(page_data)

                # Update pagination
                self.pagination.set_pagination(self.current_page, self.total_pages, self.total_items)

            logger.debug(
                f"Data loaded: page={self.current_page}/{self.total_pages}, "
                f"items={len(page_data)}, total={self.total_items}"
            )

        except Exception as e:
            logger.error(f"Error loading data: {e}", exc_info=True)
            self._display_error()

    def _display_empty_state(self):
        """Display empty state when there's no data."""
        # Hide table, pagination, and loading state
        self.table.setVisible(True)  # Keep header visible
        self.table.setRowCount(0)  # Clear any rows
        self._resize_table_to_content()  # Resize to just show header

        self.pagination.setVisible(False)
        self.loading_state.setVisible(False)

        # Show empty state
        self.empty_state.setVisible(True)

        logger.debug("Displaying empty state - no data available")

    def _display_data(self, data: List[Dict[str, Any]]):
        """
        Display data in the table.

        Args:
            data: List of row dictionaries
        """
        self._current_page_data = data
        # Hide empty state and loading state, show table/pagination
        self.empty_state.setVisible(False)
        self.loading_state.setVisible(False)
        self.table.setVisible(True)
        self.pagination.setVisible(True)


        # Clear existing rows
        self.table.setRowCount(0)

        # Add rows
        for row_idx, row_data in enumerate(data):
            self.table.insertRow(row_idx)

            # Add cells for each column
            for col_idx, column_name in enumerate(self.columns):
                if self.has_actions_column and col_idx == len(self.columns) - 1:
                    # Actions column: add skewer menu
                    # Determine actions for this row
                    if self.row_actions_callback:
                        # Dynamic actions based on row data
                        row_actions, row_action_icons = self.row_actions_callback(row_data)
                    else:
                        # Static actions
                        row_actions = self.row_actions
                        row_action_icons = self.row_action_icons

                    menu_button = SkewersMenuButton(actions=row_actions, action_icons=row_action_icons)
                    menu_button.action_triggered.connect(
                        lambda action, data=row_data: self.row_action_triggered.emit(data, action)
                    )

                    # Center the button in the cell
                    container = QWidget()
                    container_layout = QVBoxLayout(container)
                    container_layout.setContentsMargins(8, 0, 8, 0)  # Add horizontal margins
                    container_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    container_layout.addWidget(menu_button)

                    self.table.setCellWidget(row_idx, col_idx, container)
                else:
                    # Regular data cell
                    cell_value = str(row_data.get(column_name, ""))
                    
                    # Check if column should use monospaced font
                    is_monospace = any(m in column_name for m in self.monospace_columns)

                    if is_monospace:
                        # Use QLabel as cell widget to apply monospace font via inline stylesheet
                        label = QLabel(cell_value)
                        # Allow clicks to pass through to the table for row selection/highlighting
                        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                        
                        # Apply alignment
                        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                        
                        # Determine color
                        color_key = f"{column_name}_color"
                        color = row_data.get(color_key, colors.TEXT_PRIMARY)
                        
                        # Apply inline stylesheet with font-family
                        label.setStyleSheet(f'''
                            background: transparent;
                            padding-left: 5px;
                            color: {color};
                            font-family: "{get_monospace_font_family()}", monospace;
                        ''')
                        
                        self.table.setCellWidget(row_idx, col_idx, label)
                        
                        # Set empty item for cell structure, store value in UserData for sorting
                        # Tooltip is set on item (not label) since label has WA_TransparentForMouseEvents
                        item = QTableWidgetItem("")
                        item.setData(Qt.ItemDataRole.UserRole, cell_value)
                        tooltip_key = f"{column_name}_tooltip"
                        if tooltip_key in row_data:
                            item.setToolTip(row_data[tooltip_key])
                        self.table.setItem(row_idx, col_idx, item)
                    else:
                        # Regular data cell
                        color_key = f"{column_name}_color"
                        has_custom_color = color_key in row_data
                        color = row_data.get(color_key, colors.TEXT_PRIMARY)
                        
                        # Use QLabel for cells with custom colors to ensure color persists during selection
                        # (Qt's item:selected CSS overrides QTableWidgetItem.setForeground())
                        if has_custom_color:
                            label = QLabel(cell_value)
                            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                            label.setStyleSheet(f'''
                                background: transparent;
                                padding-left: 5px;
                                color: {color};
                            ''')
                            
                            self.table.setCellWidget(row_idx, col_idx, label)
                            
                            # Set empty item for cell structure, store value in UserRole for sorting
                            # Tooltip is set on item (not label) since label has WA_TransparentForMouseEvents
                            item = QTableWidgetItem("")
                            item.setData(Qt.ItemDataRole.UserRole, cell_value)
                            tooltip_key = f"{column_name}_tooltip"
                            if tooltip_key in row_data:
                                item.setToolTip(row_data[tooltip_key])
                            self.table.setItem(row_idx, col_idx, item)
                        else:
                            item = QTableWidgetItem(cell_value)
                            item.setForeground(QColor(colors.TEXT_PRIMARY))

                            # Alignment: left for content columns
                            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

                            # Check for tooltip in row data
                            tooltip_key = f"{column_name}_tooltip"
                            if tooltip_key in row_data:
                                item.setToolTip(row_data[tooltip_key])

                            self.table.setItem(row_idx, col_idx, item)


        # Update sort indicator to show current sort state
        if self.current_sort_column >= 0:
            qt_sort_order = Qt.SortOrder.AscendingOrder if self.current_sort_order == SortOrder.ASCENDING else Qt.SortOrder.DescendingOrder
            self.table.horizontalHeader().setSortIndicator(self.current_sort_column, qt_sort_order)

        # Resize table to fit content
        self._resize_table_to_content()

    def _resize_table_to_content(self):
        """Resize table height to fit all visible rows without scrolling."""
        # Calculate total height needed
        row_count = self.table.rowCount()
        row_height = self.table.verticalHeader().defaultSectionSize()
        header_height = self.table.horizontalHeader().height()

        # Add some padding for borders
        total_height = header_height + (row_count * row_height) + 2

        # Set fixed height
        self.table.setFixedHeight(total_height)

    def _display_error(self):
        """Display error state in table."""
        self.table.setRowCount(1)
        error_item = QTableWidgetItem("Error loading data")
        error_item.setForeground(QColor(colors.DANGER))
        self.table.setItem(0, 0, error_item)

    def _on_search_changed(self, search_term: str):

        self.current_search = search_term
        self.current_page = 1  # Reset to first page on search

        if self._use_async_loading:
            self.request_load()
        else:
            self._load_data()

        self.search_changed.emit(search_term)

    def _on_page_changed(self, new_page: int):

        self.current_page = new_page

        if self._use_async_loading:
            self.request_load()
        else:
            self._load_data()

        self.page_changed.emit(new_page)

    def eventFilter(self, source, event: QEvent) -> bool:
        """Handle events for the table viewport."""
        if source == self.table.viewport() and event.type() == QEvent.Type.Leave:
            self.table.clearSelection()
        return super().eventFilter(source, event)

    def _on_cell_clicked(self, row: int, column: int):
        """Handle cell click to trigger row_clicked signal."""
        if 0 <= row < len(self._current_page_data):
            self.row_clicked.emit(self._current_page_data[row])

    def _on_header_clicked(self, column: int):

        # Don't sort the Actions column
        if self.has_actions_column and column == len(self.columns) - 1:

            if self.current_sort_column >= 0:
                qt_sort_order = Qt.SortOrder.AscendingOrder if self.current_sort_order == SortOrder.ASCENDING else Qt.SortOrder.DescendingOrder
                self.table.horizontalHeader().setSortIndicator(self.current_sort_column, qt_sort_order)
            else:
                self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            return

        # If column_sort_mapping is defined, only allow sorting on mapped columns
        if self.column_sort_mapping:
            column_name = self.columns[column]
            if column_name not in self.column_sort_mapping:
                # Column not sortable - restore previous sort indicator
                if self.current_sort_column >= 0:
                    qt_sort_order = Qt.SortOrder.AscendingOrder if self.current_sort_order == SortOrder.ASCENDING else Qt.SortOrder.DescendingOrder
                    self.table.horizontalHeader().setSortIndicator(self.current_sort_column, qt_sort_order)
                else:
                    self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
                return

        # Toggle sort order if same column, otherwise default to ascending
        if self.current_sort_column == column:
            self.current_sort_order = (
                SortOrder.DESCENDING
                if self.current_sort_order == SortOrder.ASCENDING
                else SortOrder.ASCENDING
            )
        else:
            self.current_sort_column = column
            self.current_sort_order = SortOrder.ASCENDING

        # Reload data with new sort
        if self._use_async_loading:
            self.request_load()
        else:
            self._load_data()

        # Update UI sort indicator
        qt_sort_order = Qt.SortOrder.AscendingOrder if self.current_sort_order == SortOrder.ASCENDING else Qt.SortOrder.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(column, qt_sort_order)

        self.sort_changed.emit(column, self.current_sort_order.value)

    def refresh(self):
        """Refresh the table data."""
        if self._use_async_loading:
            self.request_load()
        else:
            self._load_data()

    def get_selected_row_data(self) -> Optional[Dict[str, Any]]:
        """
        Get data for the currently selected row.

        Returns:
            Row data dictionary, or None if no selection
        """
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return None

        row_idx = selected_rows[0].row()
        row_data = {}

        for col_idx, column_name in enumerate(self.columns):
            if self.has_actions_column and col_idx == len(self.columns) - 1:
                continue  # Skip Actions column

            item = self.table.item(row_idx, col_idx)
            if item:
                row_data[column_name] = item.text()

        return row_data
