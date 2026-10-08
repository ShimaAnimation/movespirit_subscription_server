class GifShootWindow(QtWidgets.QWidget):
    recordStarted = QtCore.Signal(dict)
    recordStopped = QtCore.Signal()

    EDGE_NONE = 0
    EDGE_LEFT = 1
    EDGE_RIGHT = 2
    EDGE_TOP = 4
    EDGE_BOTTOM = 8

    RESIZE_MARGIN = 8

    MIN_WIDTH = 320
    MIN_HEIGHT = 240

    def __init__(
        self,
        main_window,
        parent=None,
        editor_mode=False
    ):
        super().__init__(parent)

        self.main_window = main_window
        self.loadingWindow = LoadingWindow(self)

        Utility_QMainWindow.set_window_icon(
            self
        )

        self.first_storage_directory_dict = (
            self.main_window
            .setting_window
            .get_pix_storage_directory_info_dict()
            or {}
        )

        self.capture_type = CAPTURE_TYPE_MP4

        self.png_image = None

        self.setMinimumSize(
            self.MIN_WIDTH,
            self.MIN_HEIGHT
        )

        self.setMouseTracking(
            True
        )

        self.setFocusPolicy(
            QtCore.Qt.StrongFocus
        )

        self.editor_mode = (
            editor_mode
        )

        if self.editor_mode:
            self.setWindowFlags(
                QtCore.Qt.Window
            )

            self.setAttribute(
                QtCore.Qt.WA_TranslucentBackground,
                False
            )

        else:
            self.setWindowFlags(
                QtCore.Qt.Window
                | QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.WindowStaysOnTopHint
            )

            # =====================================================
            # Window自体を透過Windowにする
            # =====================================================

            self.setAttribute(
                QtCore.Qt.WA_TranslucentBackground,
                True
            )

            self.setAutoFillBackground(
                False
            )

            self.setObjectName(
                "GifShootWindow"
            )

            self.setStyleSheet("""
                QWidget#GifShootWindow {
                    background: transparent;
                    background-color: rgba(0, 0, 0, 0);
                }
            """)

        self.capture_preset_list = []

        self.paused = False

        self.drag_offset = None

        self.resizing = False

        self.resize_edge = (
            self.EDGE_NONE
        )

        self.resize_start_geometry = (
            QtCore.QRect()
        )

        self.resize_start_global = (
            QtCore.QPoint()
        )

        self.recording = False

        self.elapsed_second = 0.0

        self.recorder_thread = None

        self.recorded_frames = []

        self.current_frame_index = 0

        self.selected_frame_indexes = (
            set()
        )

        self.delete_undo_stack = []

        self.overlay_frame_index = None
        self.gif_thumbnail_seconds = None

        if (
            GIFEDIT_WINDOW_DICT[
                PROGRAM_NAME
            ]
            in
            self.main_window
            .window_setting_dict[
                WINDOW_INFO_KEY
            ]
        ):

            self.overlay_opacity = (
                Utility_Dict.get_value(
                    self.main_window
                    .window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    GIFEDIT_OVERLAY_OPACITY_DICT,
                    45
                )
            )

        else:

            self.overlay_opacity = 45

        self.save_resize_percent = 100

        self.play_timer = (
            QtCore.QTimer(self)
        )

        self.play_timer.timeout.connect(
            self.play_next_frame
        )

        self.timer = (
            QtCore.QTimer(self)
        )

        self.timer.timeout.connect(
            self.on_timeout
        )

        # =========================================================
        # Editor
        # =========================================================

        if self.editor_mode:

            layout = (
                QtWidgets.QVBoxLayout(
                    self
                )
            )

            layout.setContentsMargins(
                0,
                0,
                0,
                0
            )

            layout.setSpacing(
                0
            )

            self.title_bar = None
            self.control_bar = None
            self.capture_border = None
            self.capture_frame = None

        # =========================================================
        # Capture Window
        # =========================================================
        else:

            self.title_bar = TitleBarWidget(self)

            self.control_bar = ControlBarWidget(self)

            self.fps = int(
                self.control_bar.fps_combo.currentText()
            )

            self.capture_border = CaptureBorderWidget(self)

            self.capture_frame = (
                self.capture_border.capture_frame
            )

            # =========================================================
            # Main Layout
            # =========================================================

            layout = QtWidgets.QVBoxLayout(self)

            layout.setContentsMargins(
                0,
                0,
                0,
                0
            )

            layout.setSpacing(0)

            # タイトルバー
            layout.addWidget(
                self.title_bar
            )

            # 撮影領域
            # ここだけ伸縮する
            layout.addWidget(
                self.capture_border,
                1
            )

            # PNG / MP4撮影ボタン部分
            layout.addWidget(
                self.control_bar
            )

            # =========================================================
            # Mouse Tracking
            # =========================================================

            self.title_bar.setMouseTracking(
                True
            )

            self.control_bar.setMouseTracking(
                True
            )

            self.capture_border.setMouseTracking(
                True
            )

            # =========================================================
            # Event Filter
            # =========================================================

            self.title_bar.installEventFilter(
                self
            )

            self.control_bar.installEventFilter(
                self
            )

            self.capture_border.installEventFilter(
                self
            )

            self.capture_frame.installEventFilter(
                self
            )

            self.capture_border.setMouseTracking(
                True
            )

            self.capture_frame.setMouseTracking(
                True
            )

            # =========================================================
            # リサイズカーソル監視
            # =========================================================

            self.resize_cursor_timer = QtCore.QTimer(self)

            self.resize_cursor_timer.setInterval(
                30
            )

            self.resize_cursor_timer.timeout.connect(
                self.update_resize_hover_cursor
            )

            self.resize_cursor_timer.start()

            self._resize_override_cursor_active = False
            self._resize_override_cursor_shape = None

            # bottom_resize_handleには
            # eventFilterを付けない
            #
            # BottomResizeHandleWidget自身の
            # mousePressEvent / mouseMoveEvent
            # で処理する

            # =========================================================
            # TitleBar Signals
            # =========================================================

            self.title_bar.closeClicked.connect(
                self.close
            )

            self.title_bar.sizeChanged.connect(
                self.resize_capture_screen
            )

            # =========================================================
            # ControlBar Signals
            # =========================================================

            self.control_bar.discardClicked.connect(
                self.discard_record
            )

            self.title_bar.presetSaveClicked.connect(
                self.save_capture_preset
            )

            self.title_bar.presetDeleteClicked.connect(
                self.delete_capture_preset
            )

            self.title_bar.presetChanged.connect(
                self.apply_capture_preset
            )

            self.control_bar.pngClicked.connect(
                self.capture_png
            )

            self.control_bar.pauseClicked.connect(
                self.toggle_pause
            )

            self.control_bar.toggleClicked.connect(
                self.toggle_record
            )

            self.control_bar.fpsChanged.connect(
                self.set_fps
            )

            QtCore.QTimer.singleShot(
                0,
                self.update_title_bar_capture_size
            )

            QtCore.QTimer.singleShot(
                0,
                self.setFocus
            )

    def update_resize_hover_cursor(self):

        if self.editor_mode:
            return

        if (
            self.capture_border is None
            or self.capture_frame is None
        ):
            return

        # 録画中はリサイズカーソルを出さない
        if (
            self.recording
            or self.paused
        ):

            self.clear_resize_override_cursor()
            return

        # リサイズ中は現在のカーソルを維持
        if self.resizing:
            return

        # =====================================================
        # 現在のグローバルマウス位置
        # =====================================================

        global_pos = (
            QtGui.QCursor.pos()
        )

        # capture_border基準へ変換
        pos = (
            self.capture_border.mapFromGlobal(
                global_pos
            )
        )

        margin = 12

        width = (
            self.capture_border.width()
        )

        height = (
            self.capture_border.height()
        )

        # =====================================================
        # capture_border内にいるか
        # =====================================================

        inside = (
            0 <= pos.x() < width
            and
            0 <= pos.y() < height
        )

        if not inside:

            self.clear_resize_override_cursor()
            return

        # =====================================================
        # 辺判定
        # =====================================================

        is_left = (
            pos.x()
            <= margin
        )

        is_right = (
            pos.x()
            >= width - margin
        )

        is_bottom = (
            pos.y()
            >= height - margin
        )

        # =====================================================
        # Cursor決定
        # =====================================================

        # 左下
        if (
            is_left
            and is_bottom
        ):

            cursor = (
                QtCore.Qt.SizeBDiagCursor
            )

        # 右下
        elif (
            is_right
            and is_bottom
        ):

            cursor = (
                QtCore.Qt.SizeFDiagCursor
            )

        # 左端
        elif is_left:

            cursor = (
                QtCore.Qt.SizeHorCursor
            )

        # 右端
        elif is_right:

            cursor = (
                QtCore.Qt.SizeHorCursor
            )

        # 下端
        elif is_bottom:

            cursor = (
                QtCore.Qt.SizeVerCursor
            )

        else:

            self.clear_resize_override_cursor()
            return

        # =====================================================
        # Cursor変更
        # =====================================================

        if (
            not self._resize_override_cursor_active
        ):

            QtWidgets.QApplication.setOverrideCursor(
                cursor
            )

            self._resize_override_cursor_active = True
            self._resize_override_cursor_shape = cursor

        elif (
            self._resize_override_cursor_shape
            != cursor
        ):

            QtWidgets.QApplication.changeOverrideCursor(
                cursor
            )

            self._resize_override_cursor_shape = cursor

    def clear_resize_override_cursor(self):

        if not getattr(
            self,
            "_resize_override_cursor_active",
            False
        ):
            return

        QtWidgets.QApplication.restoreOverrideCursor()

        self._resize_override_cursor_active = False
        self._resize_override_cursor_shape = None

    def show_png_editor(self):
        self.setWindowTitle("PNG Edit")

        self.editor_widget = QtWidgets.QWidget(self)
        editor_layout = QtWidgets.QVBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QtWidgets.QHBoxLayout()

        self.preview_label = QtWidgets.QLabel()

        self.preview_label.setAlignment(
            QtCore.Qt.AlignCenter
        )

        # 画像サイズをWidgetの最低サイズとして扱わせない
        self.preview_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Ignored
        )

        self.preview_label.setMinimumSize(
            1,
            1
        )

        self.preview_label.setScaledContents(
            False
        )

        self.preview_label.setStyleSheet("""
        background-color: rgb(35, 35, 35);
        """)

        top_layout.addWidget(self.preview_label, 1)

        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(self.create_save_setting_widget())
        right_layout.addStretch()
        top_layout.addLayout(right_layout)

        editor_layout.addLayout(top_layout, 1)

        self.layout().addWidget(self.editor_widget)

        self.show_current_frame()
        self.check_same_file_name_exists()

        #self.resize(1200, 800)
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def capture_png(self):
        if self.recording or self.paused:
            return

        self.capture_type = CAPTURE_TYPE_PNG

        capture_rect = self.capture_rect()

        self.hide()
        QtWidgets.QApplication.processEvents()

        with mss() as sct:
            img = sct.grab(capture_rect)

        frame = Image.frombytes(
            "RGB",
            img.size,
            img.rgb
        )

        Utility_Window_Setting.save_window_pos_json(
            self,
            self.main_window.window_setting_dict,
            GIFSHOOT_WINDOW_DICT,
            True
        )

        editor = GifShootWindow(
            self.main_window,
            editor_mode=True,
        )
        if not editor in self.main_window.gifshootWindow_edit_list:
            self.main_window.gifshootWindow_edit_list.append(editor)

        editor.capture_type = CAPTURE_TYPE_PNG
        editor.png_image = frame
        editor.recorded_frames = [frame]
        editor.fps = self.fps
        editor.current_frame_index = 0
        editor.selected_frame_indexes = {0}
        editor.delete_undo_stack.clear()
        editor.overlay_frame_index = None

        editor.show_png_editor()

        self.editor_window = editor
        editor.record_window = self

    def open_reshoot_window(self):
        if self.play_timer.isActive():
            self.play_timer.stop()

        self.record_window.show()
        self.record_window.raise_()
        self.record_window.activateWindow()

        self.close()

    def showEvent(self, event):
        if self.editor_mode:
            super().showEvent(event)
            #self.showFullScreen()
            #self.showMaximized()
        else:
            if GIFSHOOT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
                self.capture_preset_list = \
                    Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFSHOOT_WINDOW_DICT[PROGRAM_NAME]], GIFSHOOT_CAPTURE_PRESET_LIST, [])
            else:
                self.capture_preset_list = []

            self._block_save = Utility_Window_Setting.window_pos_json_load(self.main_window.window_setting_dict, self, GIFSHOOT_WINDOW_DICT, (640, 480))

            if GIFSHOOT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
                window_pos = \
                    Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFSHOOT_WINDOW_DICT[PROGRAM_NAME]], WINDOW_POS_KEY, {})
                if window_pos and self.capture_preset_list:
                    is_match_preset = True
                    current_preset_dict = self.capture_preset_list[self.title_bar.preset_combo.currentIndex()]
                    if not current_preset_dict["x"] == window_pos["x"]:
                        is_match_preset = False
                    if not current_preset_dict["y"] == window_pos["y"]:
                        is_match_preset = False
                    if not current_preset_dict["width"] == window_pos["width"]:
                        is_match_preset = False
                    if not current_preset_dict["height"] == window_pos["height"]:
                        is_match_preset = False
                    if not is_match_preset:
                        self.title_bar.preset_combo.setCurrentIndex(-1)
            super().showEvent(event)

    def closeEvent(self, event):
        self.timer.stop()

        if self.recorder_thread is not None:
            try:
                self.recorder_thread.finishedRecording.disconnect(
                    self.on_recording_finished
                )
            except (TypeError, RuntimeError):
                pass

            self.recorder_thread.stop()
            self.recorder_thread.wait()
            self.recorder_thread.deleteLater()
            self.recorder_thread = None

        self.recording = False
        self.paused = False
        self.drag_offset = None
        self.resizing = False
        self.resize_edge = self.EDGE_NONE

        if not self.editor_mode:
            self.clear_resize_override_cursor()

        if self in self.main_window.gifshootWindow_edit_list:
            self.main_window.gifshootWindow_edit_list.remove(self)

        self.main_window.save_shoot_process_edit_window = None

        if self.isHidden() or not self.editor_mode:
            Utility_Window_Setting.save_window_pos_json(
                self,
                self.main_window.window_setting_dict,
                GIFSHOOT_WINDOW_DICT,
                True
            )

            if self.title_bar is not None:
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFSHOOT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFSHOOT_PRESET_COMBO_INDEX:
                        self.title_bar.preset_combo.currentIndex()
                    }
                )

            if self.control_bar is not None:
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFSHOOT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFSHOOT_FPS_COMBO_INDEX:
                        self.control_bar.fps_combo.currentIndex()
                    }
                )

            Utility_Dict.update(
                self.main_window.window_setting_dict[
                    WINDOW_INFO_KEY
                ][
                    GIFSHOOT_WINDOW_DICT[
                        PROGRAM_NAME
                    ]
                ],
                {
                    GIFSHOOT_CAPTURE_PRESET_LIST:
                    self.capture_preset_list
                }
            )

        else:
            Utility_Window_Setting.save_window_pos_json(
                self,
                self.main_window.window_setting_dict,
                GIFEDIT_WINDOW_DICT,
                True
            )

            if hasattr(
                self,
                "overlay_opacity_slider"
            ):
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFEDIT_OVERLAY_OPACITY_DICT:
                        self.overlay_opacity_slider.value()
                    }
                )

            if hasattr(
                self,
                "direct_save_radio"
            ):
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFEDIT_DIRECT_SAVE_RADIO_INDEX:
                        self.direct_save_radio.isChecked()
                    }
                )

            if hasattr(
                self,
                "direct_save_line_edit"
            ):
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFEDIT_DIRECT_SAVE_LINE_EDIT:
                        self.direct_save_line_edit.text().strip()
                    }
                )

            if hasattr(
                self,
                "registered_save_combo"
            ):
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFEDIT_REGISTERED_SAVE_COMBO_INDEX:
                        self.registered_save_combo.currentIndex()
                    }
                )

            if hasattr(
                self,
                "file_name_line_edit"
            ):
                Utility_Dict.update(
                    self.main_window.window_setting_dict[
                        WINDOW_INFO_KEY
                    ][
                        GIFEDIT_WINDOW_DICT[
                            PROGRAM_NAME
                        ]
                    ],
                    {
                        GIFEDIT_FILE_NAME_LINE_EDIT:
                        self.file_name_line_edit.text().strip()
                    }
                )

        super().closeEvent(event)

    def update_title_bar_capture_size(self):
        if self.editor_mode:
            return

        if self.title_bar is None or self.capture_frame is None:
            return

        self.title_bar.set_capture_size(
            self.capture_frame.width(),
            self.capture_frame.height()
        )

    def resize_capture_screen(self, capture_width, capture_height):
        if self.editor_mode:
            return

        capture_width = max(capture_width, self.capture_frame.minimumWidth())
        capture_height = max(capture_height, self.capture_frame.minimumHeight())

        extra_width = self.width() - self.capture_frame.width()
        extra_height = self.height() - self.capture_frame.height()

        self.resize(
            capture_width + extra_width,
            capture_height + extra_height
        )

        self.update_title_bar_capture_size()
        self.update_recorder_capture_rect()

    def set_overlay_frame(self, index):
        if index < 0 or index >= len(self.recorded_frames):
            return

        self.overlay_frame_index = index
        self.rebuild_thumbnails()
        self.show_current_frame()

        QtCore.QTimer.singleShot(0, self.setFocus)

    def clear_overlay_frame(self):
        self.overlay_frame_index = None
        self.rebuild_thumbnails()
        self.show_current_frame()

        QtCore.QTimer.singleShot(0, self.setFocus)

    def snap_thumbnail_scroll_bar(self, value=None):
        if not hasattr(self, "thumbnail_area"):
            return

        if self.thumbnail_scroll_snapping:
            return

        bar = self.thumbnail_area.horizontalScrollBar()
        step = self.thumbnail_scroll_step

        if value is None:
            value = bar.value()

        snapped_value = round(value / step) * step
        snapped_value = max(bar.minimum(), min(snapped_value, bar.maximum()))

        if snapped_value == value:
            return

        self.thumbnail_scroll_snapping = True
        bar.setValue(snapped_value)
        self.thumbnail_scroll_snapping = False

    def scroll_to_current_thumbnail(self):
        if not hasattr(self, "thumbnail_buttons"):
            return

        if self.current_frame_index >= len(self.thumbnail_buttons):
            return

        button = self.thumbnail_buttons[self.current_frame_index]

        self.thumbnail_area.ensureWidgetVisible(
            button,
            20,
            0
        )

    def move_frame_selection(self, offset):
        if not self.recorded_frames:
            return

        frame_count = len(self.recorded_frames)
        next_index = (self.current_frame_index + offset) % frame_count

        self.current_frame_index = next_index
        self.selected_frame_indexes = {next_index}

        self.update_thumbnail_states()
        self.show_current_frame()
        self.scroll_to_current_thumbnail()

        self.shift_anchor = next_index

    def save_capture_preset(self):
        description = self.title_bar.preset_line_edit.text().strip()

        if not description:
            description = f"Preset {len(self.capture_preset_list) + 1}"

        geo = self.geometry()

        fps = int(
            self.control_bar.fps_combo.currentText()
        )

        preset = {
            "description": description,
            "x": geo.x(),
            "y": geo.y(),
            "width": geo.width(),
            "height": geo.height(),
            "fps": fps,
        }

        self.capture_preset_list.append(
            preset
        )

        self.title_bar.preset_combo.addItem(
            description
        )

        self.title_bar.preset_combo.setCurrentIndex(
            self.title_bar.preset_combo.count() - 1
        )

        self.title_bar.preset_line_edit.clear()

    def delete_capture_preset(self):
        index = self.title_bar.preset_combo.currentIndex()

        if index < 0:
            return

        if index >= len(self.capture_preset_list):
            return

        del self.capture_preset_list[index]
        self.title_bar.preset_combo.removeItem(index)

    def apply_capture_preset(self, index):
        if index < 0:
            return

        if index >= len(self.capture_preset_list):
            return

        preset = self.capture_preset_list[index]

        self.setGeometry(
            preset["x"],
            preset["y"],
            preset["width"],
            preset["height"]
        )

        fps = int(
            preset.get(
                "fps",
                30
            )
        )

        fps_index = (
            self.control_bar.fps_combo.findText(
                str(fps)
            )
        )

        # プリセット内のFPSが候補にない場合も30FPSへ戻す
        if fps_index < 0:
            fps = 30
            fps_index = (
                self.control_bar.fps_combo.findText(
                    "30"
                )
            )

        if fps_index >= 0:
            self.control_bar.fps_combo.setCurrentIndex(
                fps_index
            )

        # ComboBoxのSignalに依存せず、内部値も確実に更新
        self.fps = fps

        self.update_title_bar_capture_size()
        self.update_recorder_capture_rect()

    def eventFilter(self, obj, event):

        # =========================================================
        # タイトルバーでWindow移動
        # =========================================================
        if (
            not self.editor_mode
            and obj is self.title_bar
            and not self.recording
            and not self.paused
            and hasattr(event, "globalPosition")
        ):
            if (
                event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.LeftButton
            ):
                child = self.title_bar.childAt(
                    event.position().toPoint()
                )

                if not isinstance(
                    child,
                    (
                        QtWidgets.QPushButton,
                        QtWidgets.QLineEdit,
                        QtWidgets.QComboBox,
                    )
                ):
                    self.drag_offset = (
                        event.globalPosition().toPoint()
                        - self.frameGeometry().topLeft()
                    )

                    event.accept()
                    return True

            elif (
                event.type() == QtCore.QEvent.MouseMove
                and self.drag_offset is not None
                and event.buttons() & QtCore.Qt.LeftButton
            ):
                self.move(
                    event.globalPosition().toPoint()
                    - self.drag_offset
                )

                self.update_recorder_capture_rect()

                event.accept()
                return True

            elif (
                event.type() == QtCore.QEvent.MouseButtonRelease
                and event.button() == QtCore.Qt.LeftButton
            ):
                self.drag_offset = None

                event.accept()
                return True

        is_bottom_edge = False
        is_left_edge = False
        is_right_edge = False

        # =========================================================
        # サムネイル
        # =========================================================

        if (
            hasattr(self, "thumbnail_area")
            and obj == self.thumbnail_area.viewport()
            and event.type() == QtCore.QEvent.Wheel
        ):

            bar = self.thumbnail_area.horizontalScrollBar()

            delta = event.angleDelta().y()

            if delta != 0:
                bar.setValue(
                    bar.value() - delta
                )

                event.accept()
                return True

        # =========================================================
        # Capture Border
        # =========================================================

        is_capture_widget = (
            not self.editor_mode
            and self.capture_border is not None
            and (
                obj is self.capture_border
                or obj is self.capture_frame
            )
        )

        if (
            is_capture_widget
            and hasattr(event, "globalPosition")
        ):

            global_pos = (
                event.globalPosition().toPoint()
            )

            border_pos = (
                self.capture_border.mapFromGlobal(
                    global_pos
                )
            )

            resize_margin = 12

            is_left_edge = (
                border_pos.x()
                <= resize_margin
            )

            is_right_edge = (
                border_pos.x()
                >= self.capture_border.width()
                - resize_margin
            )

            is_bottom_edge = (
                border_pos.y()
                >= self.capture_border.height()
                - resize_margin
            )

            # =====================================================
            # MouseMove
            # =====================================================
            if (
                event.type() == QtCore.QEvent.MouseMove
                and not self.resizing
                and not self.recording
                and not self.paused
            ):

                # 左端
                if is_left_edge:

                    cursor = QtCore.Qt.SizeBDiagCursor

                # 右端
                elif is_right_edge:

                    cursor = QtCore.Qt.SizeFDiagCursor

                # 下端
                elif is_bottom_edge:

                    cursor = QtCore.Qt.SizeVerCursor

                else:

                    cursor = QtCore.Qt.ArrowCursor

                self.setCursor(cursor)

                self.capture_border.setCursor(
                    cursor
                )

                self.capture_frame.setCursor(
                    cursor
                )
            # =====================================================
            # MousePress
            # =====================================================

            elif (
                event.type()
                == QtCore.QEvent.MouseButtonPress
                and event.button()
                == QtCore.Qt.LeftButton
                and not self.recording
                and not self.paused
            ):

                resize_edge = self.EDGE_NONE

                if (
                    is_left_edge
                    and is_bottom_edge
                ):

                    resize_edge = (
                        self.EDGE_LEFT
                        | self.EDGE_BOTTOM
                    )

                elif (
                    is_right_edge
                    and is_bottom_edge
                ):

                    resize_edge = (
                        self.EDGE_RIGHT
                        | self.EDGE_BOTTOM
                    )

                elif is_bottom_edge:

                    resize_edge = (
                        self.EDGE_BOTTOM
                    )

                if (
                    resize_edge
                    != self.EDGE_NONE
                ):

                    self.drag_offset = None

                    self.resizing = True

                    self.resize_edge = (
                        resize_edge
                    )

                    self.resize_start_geometry = (
                        QtCore.QRect(
                            self.geometry()
                        )
                    )

                    self.resize_start_global = (
                        global_pos
                    )

                    self.update_cursor(
                        self.resize_edge
                    )

                    self.grabMouse()

                    event.accept()

                    return True

        # =========================================================
        # 録画中
        # =========================================================

        if (
            self.recording
            or self.paused
        ):

            self.unsetCursor()

            return super().eventFilter(
                obj,
                event
            )

        # =========================================================
        # 通常MouseMove
        # =========================================================

        if (
            event.type()
            == QtCore.QEvent.MouseMove
            and not self.resizing
            and not is_capture_widget
            and hasattr(event, "globalPosition")
        ):

            local_pos = (
                self.mapFromGlobal(
                    event.globalPosition().toPoint()
                )
            )

            self.update_cursor(
                self.get_resize_edge(
                    local_pos
                )
            )

        # =========================================================
        # Leave
        # =========================================================

        elif (
            event.type()
            == QtCore.QEvent.Leave
        ):

            if not self.resizing:
                self.unsetCursor()

        return super().eventFilter(
            obj,
            event
        )

    def discard_record(self):
        if not self.recording:
            return

        self.recording = False

        self.timer.stop()

        self.control_bar.set_recording(False)
        self.capture_border.set_recording(False)

        if self.recorder_thread is not None:
            try:
                self.recorder_thread.finishedRecording.disconnect(
                    self.on_recording_finished
                )
            except (TypeError, RuntimeError):
                pass

            self.recorder_thread.stop()
            self.recorder_thread.wait()
            self.recorder_thread.deleteLater()
            self.recorder_thread = None

        self.paused = False
        self.control_bar.pause_button.setText("Ⅱ Pause")

        self.control_bar.set_elapsed_time(0.0)
        self.control_bar.set_frame_count(0)
        self.recordStopped.emit()

    def toggle_pause(self):
        if not self.recording:
            return

        self.paused = not self.paused

        if self.recorder_thread is not None:
            self.recorder_thread.toggle_pause()

        if self.paused:
            self.pause_start_time = time.perf_counter()
            self.control_bar.pause_button.setText("▶ Resume")
        else:
            self.pause_elapsed += (
                time.perf_counter() - self.pause_start_time
            )
            self.pause_start_time = None
            self.control_bar.pause_button.setText("Ⅱ Pause")

    def set_fps(self, fps: int):
        self.fps = fps

    def toggle_record(self):
        if self.recording:
            self.stop_record()
        else:
            self.start_record()

    def update_recorder_capture_rect(self):
        if self.recording and self.recorder_thread is not None:
            self.recorder_thread.set_capture_rect(
                self.capture_rect()
            )

    def create_save_setting_widget(self):
        widget = QtWidgets.QWidget()
        widget.setFixedWidth(360)

        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)

        #layout.addStretch()

        # ---------- 再撮影 ----------
        title_layout_layer = QtWidgets.QHBoxLayout()
        title_layout_layer.setContentsMargins(0, 0, 0, 6)
        title_layout_layer.setSpacing(8)

        left_line = QtWidgets.QFrame()
        left_line.setFrameShape(QtWidgets.QFrame.HLine)
        left_line.setFrameShadow(QtWidgets.QFrame.Plain)

        title_label = QtWidgets.QLabel({
            JAPANESE: "MP4 撮影",
            KOREAN: "MP4 촬영",
            ENGLISH: "Record MP4",
            SIMPLIFIED_CHINESE: "MP4 录制",
            TRADITIONAL_CHINESE: "MP4 錄製"
        }[self.main_window.text_language])
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        title_label.setStyleSheet("""
        font-weight: bold;
        color: rgb(210, 210, 210);
        background: transparent;
        """)

        right_line = QtWidgets.QFrame()
        right_line.setFrameShape(QtWidgets.QFrame.HLine)
        right_line.setFrameShadow(QtWidgets.QFrame.Plain)

        title_layout_layer.addWidget(left_line)
        title_layout_layer.addWidget(title_label)
        title_layout_layer.addWidget(right_line)

        layout.addLayout(title_layout_layer)

        self.reshoot_button = QtWidgets.QPushButton({
            JAPANESE: "再撮影",
            KOREAN: "재촬영",
            ENGLISH: "Retake",
            SIMPLIFIED_CHINESE: "重新拍摄",
            TRADITIONAL_CHINESE: "重新拍攝"
        }[self.main_window.text_language])
        self.reshoot_button.setFixedHeight(25)
        self.reshoot_button.setStyleSheet(Utility_ButtonStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.reshoot_button, {
            JAPANESE: "<  撮影したものを削除し、撮影モードに戻る",
            KOREAN: "<  촬영한 내용을 삭제하고 촬영 모드로 돌아가기",
            ENGLISH: "<  Delete the captured content and return to capture mode.",
            SIMPLIFIED_CHINESE: "<  删除已拍摄的内容并返回拍摄模式。",
            TRADITIONAL_CHINESE: "<  刪除已拍攝的內容並返回拍攝模式。"
        }[self.main_window.text_language]
        )

        layout.addWidget(self.reshoot_button)

        self.reshoot_button.clicked.connect(
            self.open_reshoot_window
        )

        if self.capture_type == CAPTURE_TYPE_MP4:
            # ---------- 半透明レイヤー不透明度 ----------
            title_layout_layer = QtWidgets.QHBoxLayout()
            title_layout_layer.setContentsMargins(0, 0, 0, 6)
            title_layout_layer.setSpacing(8)

            left_line = QtWidgets.QFrame()
            left_line.setFrameShape(QtWidgets.QFrame.HLine)
            left_line.setFrameShadow(QtWidgets.QFrame.Plain)

            title_label = QtWidgets.QLabel({
                JAPANESE: "半透明レイヤー",
                KOREAN: "반투명 레이어",
                ENGLISH: "Overlay",
                SIMPLIFIED_CHINESE: "半透明图层",
                TRADITIONAL_CHINESE: "半透明圖層"
            }[self.main_window.text_language])
            title_label.setAlignment(QtCore.Qt.AlignCenter)
            title_label.setStyleSheet("""
            font-weight: bold;
            color: rgb(210, 210, 210);
            background: transparent;
            """)

            right_line = QtWidgets.QFrame()
            right_line.setFrameShape(QtWidgets.QFrame.HLine)
            right_line.setFrameShadow(QtWidgets.QFrame.Plain)

            title_layout_layer.addWidget(left_line)
            title_layout_layer.addWidget(title_label)
            title_layout_layer.addWidget(right_line)

            layout.addLayout(title_layout_layer)

            explanation_label = QtWidgets.QLabel(
                {
                    JAPANESE: "連番画像を右クリックで画像を半透明レイヤーにして固定できます",
                    KOREAN: "연속 이미지를 우클릭하면 이미지를 반투명 레이어로 고정할 수 있습니다",
                    ENGLISH: "Right-click a frame to pin it as a transparent overlay.",
                    SIMPLIFIED_CHINESE: "右键单击连续图像，可将该图像固定为半透明图层。",
                    TRADITIONAL_CHINESE: "右鍵點擊連續影像，可將該影像固定為半透明圖層。"
                }[self.main_window.text_language]
            )
            explanation_label.setAlignment(QtCore.Qt.AlignCenter)
            explanation_label.setStyleSheet("""
            font-weight: bold;
            color: rgb(210, 210, 210);
            background: transparent;
            """)

            layout.addWidget(explanation_label)

            self.overlay_opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.overlay_opacity_slider.setRange(0, 100)
            self.overlay_opacity_slider.setValue(self.overlay_opacity)
            self.overlay_opacity_slider.setFixedHeight(24)
            ToolTip_Alt_Manager.instance().register(self.overlay_opacity_slider, {
                JAPANESE: "<  撮影した動画の連番画像内で選択状態の画像を透過して固定表示させて、他のフレームとの画像差分を確認できるようにする",
                KOREAN: "<  촬영한 동영상의 연속 이미지에서 선택한 이미지를 반투명으로 고정 표시하여 다른 프레임과의 이미지 차이를 확인할 수 있도록 설정",
                ENGLISH: "<  Make the selected frame from the captured image sequence semi-transparent and keep it displayed as an overlay, allowing you to compare the differences with other frames.",
                SIMPLIFIED_CHINESE: "<  将拍摄视频的连续图像中选中的图像设为半透明并固定显示，以便与其他帧进行图像差异比较。",
                TRADITIONAL_CHINESE: "<  將拍攝影片的連續影像中選取的影像設為半透明並固定顯示，以便與其他幀進行影像差異比較。"
            }[self.main_window.text_language]
            )

            self.overlay_opacity_value_label = QtWidgets.QLabel(
                f"{self.overlay_opacity}%"
            )
            self.overlay_opacity_value_label.setFixedWidth(27)
            self.overlay_opacity_value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.overlay_opacity_value_label.setStyleSheet("""
            color: white;
            background: transparent;
            """)

            overlay_slider_layout = QtWidgets.QHBoxLayout()
            overlay_slider_layout.setContentsMargins(0, 0, 0, 8)
            overlay_slider_layout.setSpacing(6)
            overlay_slider_layout.addWidget(self.overlay_opacity_value_label)
            overlay_slider_layout.addWidget(self.overlay_opacity_slider)

            layout.addLayout(overlay_slider_layout)

            self.overlay_opacity_slider.valueChanged.connect(
                self.set_overlay_opacity
            )

        if self.capture_type == CAPTURE_TYPE_MP4:
            # ---------- サイズ変更 ----------
            title_layout_resize = QtWidgets.QHBoxLayout()
            title_layout_resize.setContentsMargins(0, 0, 0, 6)
            title_layout_resize.setSpacing(8)

            left_line = QtWidgets.QFrame()
            left_line.setFrameShape(QtWidgets.QFrame.HLine)
            left_line.setFrameShadow(QtWidgets.QFrame.Plain)

            title_label = QtWidgets.QLabel(
                {
                    JAPANESE: "画面サイズ変更",
                    KOREAN: "화면 크기 변경",
                    ENGLISH: "Resize Screen",
                    SIMPLIFIED_CHINESE: "调整画面大小",
                    TRADITIONAL_CHINESE: "調整畫面大小"
                }[self.main_window.text_language]
            )
            title_label.setAlignment(QtCore.Qt.AlignCenter)
            title_label.setStyleSheet("""
            font-weight: bold;
            color: rgb(210, 210, 210);
            background: transparent;
            """)

            right_line = QtWidgets.QFrame()
            right_line.setFrameShape(QtWidgets.QFrame.HLine)
            right_line.setFrameShadow(QtWidgets.QFrame.Plain)

            title_layout_resize.addWidget(left_line)
            title_layout_resize.addWidget(title_label)
            title_layout_resize.addWidget(right_line)

            layout.addLayout(title_layout_resize)

            self.save_resize_size_label = QtWidgets.QLabel()
            self.save_resize_size_label.setFixedWidth(65)
            self.save_resize_size_label.setAlignment(
                QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
            )
            self.save_resize_size_label.setStyleSheet("""
            color: white;
            background: transparent;
            """)

            self.save_resize_percent_label = QtWidgets.QLabel()
            self.save_resize_percent_label.setFixedWidth(42)
            self.save_resize_percent_label.setAlignment(
                QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
            )
            self.save_resize_percent_label.setStyleSheet("""
            color: white;
            background: transparent;
            """)

            self.save_resize_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.save_resize_slider.setRange(25, 100)
            self.save_resize_slider.setValue(self.save_resize_percent)
            self.save_resize_slider.setFixedHeight(24)
            ToolTip_Alt_Manager.instance().register(self.save_resize_slider, {
                JAPANESE: "<  左の白色の縦棒を調整後の動画サイズと見立てて、撮影した動画を拡縮する",
                KOREAN: "<  왼쪽의 흰색 세로 막대를 조정 후의 동영상 크기로 보고, 촬영한 동영상을 확대/축소",
                ENGLISH: "<  Use the white vertical bar on the left as a reference for the adjusted video size, and scale the captured video accordingly.",
                SIMPLIFIED_CHINESE: "<  将左侧的白色竖条作为调整后的视频尺寸参考，对拍摄的视频进行缩放。",
                TRADITIONAL_CHINESE: "<  將左側的白色直條作為調整後的影片尺寸參考，對拍攝的影片進行縮放。"
            }[self.main_window.text_language]
            )

            resize_slider_layout = QtWidgets.QHBoxLayout()
            #resize_slider_layout.setContentsMargins(0, 0, 0, 8)
            #resize_slider_layout.setSpacing(6)

            resize_slider_layout.addWidget(self.save_resize_size_label)
            resize_slider_layout.addWidget(self.save_resize_percent_label)
            resize_slider_layout.addWidget(self.save_resize_slider, 1)

            layout.addLayout(resize_slider_layout)

            self.save_resize_slider.valueChanged.connect(
                self.set_save_resize_percent
            )
            self.set_save_resize_percent(self.save_resize_percent)

        # ---------- 保存設定タイトル ----------
        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 6)
        title_layout.setSpacing(8)

        left_line = QtWidgets.QFrame()
        left_line.setFrameShape(QtWidgets.QFrame.HLine)
        left_line.setFrameShadow(QtWidgets.QFrame.Plain)

        is_png = self.capture_type == "png"

        title_label = QtWidgets.QLabel(
            {
                JAPANESE: "PNG 保存" if is_png else "MP4 保存",
                KOREAN: "PNG 저장" if is_png else "MP4 저장",
                ENGLISH: "Save PNG" if is_png else "Save MP4",
                SIMPLIFIED_CHINESE: "保存 PNG" if is_png else "保存 MP4",
                TRADITIONAL_CHINESE: "儲存 PNG" if is_png else "儲存 MP4",
            }[self.main_window.text_language]
        )
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        title_label.setStyleSheet("""
        font-weight: bold;
        color: rgb(210, 210, 210);
        background: transparent;
        """)

        right_line = QtWidgets.QFrame()
        right_line.setFrameShape(QtWidgets.QFrame.HLine)
        right_line.setFrameShadow(QtWidgets.QFrame.Plain)

        title_layout.addWidget(left_line)
        title_layout.addWidget(title_label)
        title_layout.addWidget(right_line)

        layout.addLayout(title_layout)

        # --- 直接フォルダ指定 ---
        self.direct_save_radio = QtWidgets.QRadioButton()
        ToolTip_Alt_Manager.instance().register(self.direct_save_radio, {
            JAPANESE: "<  入出力フォルダ設定ビューで登録していないフォルダに動画を保存する",
            KOREAN: "<  입출력 폴더 설정 뷰에 등록되지 않은 폴더에 동영상을 저장",
            ENGLISH: "<  Save the video to a folder that is not registered in the Input/Output Folder Settings window.",
            SIMPLIFIED_CHINESE: "<  将视频保存到未在输入/输出文件夹设置窗口中注册的文件夹。",
            TRADITIONAL_CHINESE: "<  將影片儲存到未在輸入/輸出資料夾設定視窗中註冊的資料夾。"
        }[self.main_window.text_language]
        )

        self.direct_save_line_edit = QtWidgets.QLineEdit()
        self.direct_save_line_edit.setPlaceholderText({
            JAPANESE: "保存先フォルダパス",
            KOREAN: "저장 폴더 경로",
            ENGLISH: "Save Folder",
            SIMPLIFIED_CHINESE: "保存文件夹路径",
            TRADITIONAL_CHINESE: "儲存資料夾路徑"
        }[self.main_window.text_language])
        self.direct_save_line_edit.setStyleSheet(Utility_qLineEditStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.direct_save_line_edit, {
            JAPANESE: "<  保存するフォルダパスを表示する",
            KOREAN: "<  저장할 폴더 경로를 표시",
            ENGLISH: "<  Display the folder path where the video will be saved.",
            SIMPLIFIED_CHINESE: "<  显示视频保存到的文件夹路径。",
            TRADITIONAL_CHINESE: "<  顯示影片將儲存到的資料夾路徑。"
        }[self.main_window.text_language]
        )

        if GIFEDIT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
            direct_save_line_edit_text = \
                Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFEDIT_WINDOW_DICT[PROGRAM_NAME]], GIFEDIT_DIRECT_SAVE_LINE_EDIT, "")
            self.direct_save_line_edit.setText(direct_save_line_edit_text)

        self.select_folder_button = QtWidgets.QPushButton()
        self.select_folder_button.setFixedWidth(34)
        self.select_folder_button.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_DirIcon)
        )
        self.select_folder_button.setStyleSheet(Utility_ButtonStyles.standard())

        direct_layout = QtWidgets.QHBoxLayout()
        direct_layout.addWidget(self.direct_save_radio)
        direct_layout.addWidget(self.direct_save_line_edit)
        direct_layout.addWidget(self.select_folder_button)

        # --- 登録済み保存先 ---
        self.registered_save_radio = QtWidgets.QRadioButton()
        ToolTip_Alt_Manager.instance().register(self.registered_save_radio, {
            JAPANESE: "<  入出力フォルダ設定ビューで登録しているフォルダを選択し、動画を保存する",
            KOREAN: "<  입출력 폴더 설정 뷰에 등록된 폴더를 선택하여 동영상을 저장",
            ENGLISH: "<  Select a folder registered in the Input/Output Folder Settings window and save the video there.",
            SIMPLIFIED_CHINESE: "<  选择在输入/输出文件夹设置窗口中注册的文件夹，并将视频保存到该文件夹。",
            TRADITIONAL_CHINESE: "<  選擇在輸入/輸出資料夾設定視窗中註冊的資料夾，並將影片儲存到該資料夾。"
        }[self.main_window.text_language]
        )

        if GIFEDIT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
            direct_save_radio_checked = \
                Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFEDIT_WINDOW_DICT[PROGRAM_NAME]], GIFEDIT_DIRECT_SAVE_RADIO_INDEX, False)
            if direct_save_radio_checked:
                self.direct_save_radio.setChecked(True)
            else:
                self.direct_save_radio.setChecked(False)
                self.registered_save_radio.setChecked(True)
        else:
            self.direct_save_radio.setChecked(True)

        self.registered_save_combo = QComboBox_Custom(self)
        self.registered_save_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Fixed
        )
        for directory_path, description in self.first_storage_directory_dict.items():
            self.registered_save_combo.addItem(
                f"{description} : {directory_path}",
                str(directory_path)
            )
        ToolTip_Alt_Manager.instance().register(self.registered_save_combo, {
            JAPANESE: "<  保存するフォルダパスを表示する",
            KOREAN: "<  저장할 폴더 경로를 표시",
            ENGLISH: "<  Display the folder path where the video will be saved.",
            SIMPLIFIED_CHINESE: "<  显示视频保存到的文件夹路径。",
            TRADITIONAL_CHINESE: "<  顯示影片將儲存到的資料夾路徑。"
        }[self.main_window.text_language]
        )

        if GIFEDIT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
            registered_save_combo_index = \
                Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFEDIT_WINDOW_DICT[PROGRAM_NAME]], GIFEDIT_REGISTERED_SAVE_COMBO_INDEX, 0)
            if self.registered_save_combo.count() - 1 < registered_save_combo_index:
                pass
            else:
                self.registered_save_combo.setCurrentIndex(registered_save_combo_index)

        registered_layout = QtWidgets.QHBoxLayout()
        registered_layout.addWidget(self.registered_save_radio)
        registered_layout.addWidget(self.registered_save_combo, 1)

        self.file_name_warning_label = QtWidgets.QLabel("")
        self.file_name_warning_label.setStyleSheet("""
        color: red;
        background: transparent;
        """)
        self.file_name_warning_label.setFixedHeight(18)

        # --- ファイル名 ---
        self.new_file_name_button = QtWidgets.QPushButton({
            JAPANESE: "ファイル名の新規作成",
            KOREAN: "파일 이름 새로 만들기",
            ENGLISH: "New Name",
            SIMPLIFIED_CHINESE: "新建文件名",
            TRADITIONAL_CHINESE: "建立新檔名"
        }[self.main_window.text_language])
        #self.new_file_name_button.setFixedWidth(132)
        self.new_file_name_button.setStyleSheet(Utility_ButtonStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.new_file_name_button, {
            JAPANESE: "<  保存するフォルダ内で、同名がないファイル名を設定する",
            KOREAN: "<  저장 폴더 안에서 중복되지 않는 파일 이름을 설정",
            ENGLISH: "<  Set a file name that does not already exist in the selected save folder.",
            SIMPLIFIED_CHINESE: "<  设置一个在所选保存文件夹中尚不存在的文件名。",
            TRADITIONAL_CHINESE: "<  設定一個在所選儲存資料夾中尚不存在的檔案名稱。"
        }[self.main_window.text_language]
        )

        self.file_name_line_edit = QtWidgets.QLineEdit()
        self.file_name_line_edit.setPlaceholderText({
            JAPANESE: "ファイル名",
            KOREAN: "파일 이름",
            ENGLISH: "File Name",
            SIMPLIFIED_CHINESE: "文件名",
            TRADITIONAL_CHINESE: "檔案名稱"
        }[self.main_window.text_language])
        self.file_name_line_edit.setStyleSheet(Utility_qLineEditStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.file_name_line_edit, {
            JAPANESE: "<  保存するファイル名を表示する",
            KOREAN: "<  저장할 파일 이름을 표시",
            ENGLISH: "<  Display the file name to be saved.",
            SIMPLIFIED_CHINESE: "<  显示要保存的文件名。",
            TRADITIONAL_CHINESE: "<  顯示要儲存的檔案名稱。"
        }[self.main_window.text_language]
        )

        if GIFEDIT_WINDOW_DICT[PROGRAM_NAME] in self.main_window.window_setting_dict[WINDOW_INFO_KEY]:
            file_name_line_edit_text = \
                Utility_Dict.get_value(self.main_window.window_setting_dict[WINDOW_INFO_KEY][GIFEDIT_WINDOW_DICT[PROGRAM_NAME]], GIFEDIT_FILE_NAME_LINE_EDIT, "")
            self.file_name_line_edit.setText(file_name_line_edit_text)

        file_name_layout = QtWidgets.QHBoxLayout()
        file_name_layout.addWidget(self.new_file_name_button)
        file_name_layout.addWidget(self.file_name_line_edit)

        # --- 保存 ---
        self.save_gif_button = QtWidgets.QPushButton(
            {
                JAPANESE: "編集内容を保存" if self.capture_type == CAPTURE_TYPE_MP4 else "保存",
                KOREAN: "편집 내용 저장" if self.capture_type == CAPTURE_TYPE_MP4 else "저장",
                ENGLISH: "Save Edited Content" if self.capture_type == CAPTURE_TYPE_MP4 else "Save PNG",
                SIMPLIFIED_CHINESE: "保存编辑内容" if self.capture_type == CAPTURE_TYPE_MP4 else "保存PNG",
                TRADITIONAL_CHINESE: "儲存編輯內容" if self.capture_type == CAPTURE_TYPE_MP4 else "儲存PNG"
            }[self.main_window.text_language]
        )

        self.save_gif_button.setFixedHeight(25)
        self.save_gif_button.setStyleSheet(Utility_ButtonStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.save_gif_button, {
            JAPANESE: "<  下の連番画像の内容でフォルダに保存する",
            KOREAN: "<  아래의 연속 이미지 내용으로 폴더에 저장",
            ENGLISH: "<  Save the contents of the image sequence below to the selected folder.",
            SIMPLIFIED_CHINESE: "<  将下方连续图像的内容保存到所选文件夹。",
            TRADITIONAL_CHINESE: "<  將下方連續影像的內容儲存到所選資料夾。"
        }[self.main_window.text_language]
        )

        self.save_thumbnail_5sec_button = None
        if self.capture_type == CAPTURE_TYPE_MP4:
            self.save_thumbnail_5sec_button = QtWidgets.QPushButton(
                {
                    JAPANESE: "サムネを再作成する為最初の1秒だけ保存",
                    KOREAN: "썸네일을 다시 생성하기 위해 처음 1초만 저장",
                    ENGLISH: "Save Only the First 1 Seconds to Recreate the Thumbnail",
                    SIMPLIFIED_CHINESE: "仅保存最初1秒以重新创建缩略图",
                    TRADITIONAL_CHINESE: "僅儲存最初1秒以重新建立縮圖"
                }[self.main_window.text_language]
            )
            self.save_thumbnail_5sec_button.setFixedHeight(25)
            self.save_thumbnail_5sec_button.setStyleSheet(Utility_ButtonStyles.standard())
            ToolTip_Alt_Manager.instance().register(self.save_thumbnail_5sec_button, {
                JAPANESE: "<  長尺の動画を保存処理するとサムネ作成に時間がかかるため、処理時間を短くするために動画開始1秒だけをサムネ作成する",
                KOREAN: "<  긴 동영상을 저장하면 썸네일 생성에 시간이 오래 걸리므로, 처리 시간을 줄이기 위해 동영상 시작 후 1초 구간만 사용하여 썸네일을 생성",
                ENGLISH: "<  To reduce thumbnail generation time when saving a long video, create the thumbnail using only the first 1 seconds of the video.",
                SIMPLIFIED_CHINESE: "<  保存较长的视频时，生成缩略图需要较长时间，因此仅使用视频开始后的1秒来生成缩略图，以缩短处理时间。",
                TRADITIONAL_CHINESE: "<  儲存較長的影片時，產生縮圖需要較長時間，因此僅使用影片開始後的1秒來產生縮圖，以縮短處理時間。"
            }[self.main_window.text_language]
            )

        layout.addLayout(direct_layout)
        layout.addLayout(registered_layout)
        layout.addLayout(file_name_layout)
        layout.addWidget(self.file_name_warning_label)
        layout.addWidget(self.save_gif_button)

        if self.save_thumbnail_5sec_button is not None:
            layout.addWidget(self.save_thumbnail_5sec_button)

        self.select_folder_button.clicked.connect(self.select_direct_save_directory)
        self.new_file_name_button.clicked.connect(self.set_auto_file_name)
        self.save_gif_button.clicked.connect(self.save_recorded_file)

        if self.save_thumbnail_5sec_button is not None:
            self.save_thumbnail_5sec_button.clicked.connect(self.save_recorded_file_thumbnail_1sec)

        if self.main_window.save_shoot_process_edit_window:
            if self != self.main_window.save_shoot_process_edit_window:
                self.save_gif_button.setEnabled(False)
                self.save_gif_button.setText(
                    {
                        JAPANESE: "別のMP4を保存処理中...",
                        KOREAN: "다른 MP4를 저장 처리 중...",
                        ENGLISH: "Saving...",
                        SIMPLIFIED_CHINESE: "正在保存其他MP4...",
                        TRADITIONAL_CHINESE: "正在儲存其他MP4..."
                    }[self.main_window.text_language]
                )
                if self.save_thumbnail_5sec_button is not None:
                    self.save_thumbnail_5sec_button.setEnabled(False)

        self.file_name_line_edit.textChanged.connect(
            self.check_same_file_name_exists
        )

        self.direct_save_line_edit.textChanged.connect(
            self.check_same_file_name_exists
        )


        self.registered_save_combo.currentIndexChanged.connect(
            self.check_same_file_name_exists
        )

        self.direct_save_radio.toggled.connect(
            self.check_same_file_name_exists
        )

        self.registered_save_radio.toggled.connect(
            self.check_same_file_name_exists
        )

        widget.setStyleSheet("""
        QFrame {
            color: rgb(90, 90, 90);
        }

        QRadioButton::indicator {
            width: 16px;
            height: 16px;
        }

        QRadioButton::indicator:unchecked {
            border: 1px solid rgb(120,120,120);
            border-radius: 8px;
            background: rgb(220,220,220);
        }

        QRadioButton::indicator:checked {
            border: 1px solid rgb(220,180,0);
            border-radius: 8px;
            background: rgb(255,245,180);
        }
        QComboBox QAbstractItemView {
            background-color: rgb(95, 95, 95);
            color: white;
            border: 1px solid rgb(120, 120, 120);
            selection-background-color: rgb(120, 170, 255);
            selection-color: black;
        }
        QComboBox QAbstractItemView::item:selected {
            background-color: rgb(190, 230, 255);
            color: black;
        }

        QComboBox QAbstractItemView::item:hover {
            background-color: rgb(150, 210, 255);
            color: black;
        }
        """)

        return widget

    def save_recorded_file(self):
        self.gif_thumbnail_seconds = None
        self.start_save_recorded_file_process(self.save_gif_button)

    def save_recorded_file_thumbnail_1sec(self):
        self.gif_thumbnail_seconds = 1
        self.start_save_recorded_file_process(self.save_thumbnail_5sec_button)

    def start_save_recorded_file_process(self, clicked_button):
        self.main_window.save_shoot_process_edit_window = self

        if hasattr(self, "save_gif_button") and self.save_gif_button is not None:
            self.save_gif_button.setEnabled(False)
        if hasattr(self, "save_thumbnail_5sec_button") and self.save_thumbnail_5sec_button is not None:
            self.save_thumbnail_5sec_button.setEnabled(False)

        clicked_button.setText(
            {
                JAPANESE: "保存処理中...",
                KOREAN: "저장 처리 중...",
                ENGLISH: "Saving...",
                SIMPLIFIED_CHINESE: "保存处理中...",
                TRADITIONAL_CHINESE: "儲存處理中..."
            }[self.main_window.text_language]
        )
        clicked_button.setStyleSheet("""
            QPushButton {
                color: black;
                background-color: rgb(200, 200, 50);
            }
        """)

        self.loadingWindow.show()
        self.loadingWindow.progress.setValue(0)
        Utility_QMainWindow.raise_window(self.main_window)
        QtCore.QTimer.singleShot(200, self.save_recorded_file_wrapper)

    def save_recorded_file_wrapper(self):

        if getattr(
            self,
            "is_opened_from_mp4",
            False
        ):
            self.save_recorded_gif()
            return

        if self.capture_type == "png":
            self.save_recorded_png()

        else:
            self.save_recorded_mp4()

    def save_recorded_png(self):
        if not self.recorded_frames:
            return

        directory_text = self.get_active_save_directory()
        file_name = self.file_name_line_edit.text().strip()
        if not directory_text:
            return
        if not file_name:
            file_name = self.set_auto_file_name()

        self.loadingWindow.show()
        QtWidgets.QApplication.processEvents()
        self.loadingWindow.progress.setValue(0)

        directory = Path(directory_text)
        directory.mkdir(parents=True, exist_ok=True)

        if not file_name.lower().endswith(".png"):
            file_name += ".png"

        save_path = directory / file_name

        frame = self.recorded_frames[0]

        self.loadingWindow.progress.setValue(50)

        frame.save(save_path)

        self.close()

        self.loadingWindow.progress.setValue(100)
        self.loadingWindow.hide()

        self.main_window.reload_show_image_next_wrapper()

    def set_overlay_opacity(self, value):
        self.overlay_opacity = value

        if hasattr(self, "overlay_opacity_value_label"):
            self.overlay_opacity_value_label.setText(f"{value}%")

        self.show_current_frame()
        QtCore.QTimer.singleShot(0, self.setFocus)

    def set_save_resize_percent(self, value):
        self.save_resize_percent = value

        if self.recorded_frames:
            base_width = self.recorded_frames[0].width
            base_height = self.recorded_frames[0].height

            width = max(1, int(base_width * value / 100))
            height = max(1, int(base_height * value / 100))

            self.save_resize_size_label.setText(f"{width} × {height}px")

            if hasattr(self, "resize_compare_bar"):
                self.resize_compare_bar.set_resize_info(
                    base_height,
                    value
                )

        self.save_resize_percent_label.setText(f"{value}%")

        QtCore.QTimer.singleShot(0, self.setFocus)

    def show_frame_editor(self):
        self.setWindowTitle(GIFEDIT_WINDOW_DICT[SHOW_TITLE][self.main_window.text_language])

        self.editor_widget = QtWidgets.QWidget(self)
        editor_layout = QtWidgets.QVBoxLayout(self.editor_widget)
        editor_layout.setContentsMargins(10, 10, 10, 10)

        self.preview_label = QtWidgets.QLabel()

        self.preview_label.setAlignment(
            QtCore.Qt.AlignCenter
        )

        # 画像サイズをWidgetの最低サイズとして扱わせない
        self.preview_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored,
            QtWidgets.QSizePolicy.Ignored
        )

        self.preview_label.setMinimumSize(
            1,
            1
        )

        self.preview_label.setScaledContents(
            False
        )

        self.preview_label.setStyleSheet("""
        background-color: rgb(35, 35, 35);
        """)

        self.thumbnail_area = QtWidgets.QScrollArea()
        self.thumbnail_area.setWidgetResizable(True)
        self.thumbnail_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.thumbnail_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.thumbnail_area.setFixedHeight(215)

        self.thumbnail_container = QtWidgets.QWidget()
        self.thumbnail_layout = QtWidgets.QHBoxLayout(self.thumbnail_container)
        self.thumbnail_layout.setContentsMargins(4, 4, 4, 4)
        self.thumbnail_layout.setSpacing(4)

        self.thumbnail_area.setWidget(self.thumbnail_container)
        self.thumbnail_area.viewport().installEventFilter(self)

        self.thumbnail_scroll_step = 166
        self.thumbnail_scroll_snapping = False

        bar = self.thumbnail_area.horizontalScrollBar()
        bar.setSingleStep(self.thumbnail_scroll_step)
        bar.setPageStep(self.thumbnail_scroll_step)
        bar.valueChanged.connect(self.snap_thumbnail_scroll_bar)

        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(6)

        top_layout = QtWidgets.QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(10)

        preview_layout.setSpacing(6)

        self.resize_compare_bar = ResizeCompareBarWidget()

        preview_image_layout = QtWidgets.QHBoxLayout()
        preview_image_layout.setContentsMargins(0, 0, 0, 0)
        preview_image_layout.setSpacing(8)

        preview_image_layout.addWidget(self.preview_label, 1)
        preview_image_layout.addWidget(self.resize_compare_bar)

        preview_layout.addLayout(preview_image_layout, 1)

        self.preview_info_label = QtWidgets.QLabel()
        self.preview_info_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_info_label.setStyleSheet("""
        color: white;
        background: transparent;
        font-size: 14px;
        font-weight: bold;
        """)

        preview_layout.addWidget(self.preview_info_label)

        self.first_frame_button = QtWidgets.QPushButton("|<")
        self.first_frame_button.setFixedWidth(50)
        self.first_frame_button.setStyleSheet(Utility_ButtonStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.first_frame_button, {
            JAPANESE: "<  0フレームに移動する",
            KOREAN: "<  0프레임으로 이동",
            ENGLISH: "<  Move to frame 0.",
            SIMPLIFIED_CHINESE: "<  移动到第0帧。",
            TRADITIONAL_CHINESE: "<  移動到第0幀。"
        }[self.main_window.text_language]
        )

        self.editor_play_button = QtWidgets.QPushButton("▶")
        self.editor_play_button.setFixedWidth(50)
        self.editor_play_button.setStyleSheet(Utility_ButtonStyles.standard())
        ToolTip_Alt_Manager.instance().register(self.editor_play_button, {
            JAPANESE: "<  再生/停止をする",
            KOREAN: "<  재생/정지",
            ENGLISH: "<  Play / Pause",
            SIMPLIFIED_CHINESE: "<  播放/暂停",
            TRADITIONAL_CHINESE: "<  播放/暫停"
        }[self.main_window.text_language]
        )

        preview_control_layout = QtWidgets.QHBoxLayout()
        preview_control_layout.addStretch()
        preview_control_layout.addWidget(self.first_frame_button)
        preview_control_layout.addWidget(self.editor_play_button)
        preview_control_layout.addStretch()

        preview_layout.addLayout(preview_control_layout)

        top_layout.addLayout(preview_layout, 1)

        self.first_frame_button.clicked.connect(
            self.move_to_first_frame
        )

        self.editor_play_button.clicked.connect(
            self.toggle_play
        )

        right_layout = QtWidgets.QVBoxLayout()
        right_layout.addWidget(self.create_save_setting_widget())
        right_layout.addStretch()

        top_layout.addLayout(right_layout)

        editor_layout.addLayout(top_layout, 1)
        editor_layout.addWidget(self.thumbnail_area)

        self.layout().addWidget(self.editor_widget)

        self.rebuild_thumbnails()
        self.show_current_frame()

        self.check_same_file_name_exists()

        # =====================================================
        # 編集ビューを開いた時は0フレーム目を選択
        # =====================================================
        self.move_to_first_frame()

        # 左右キーをすぐ使えるようにWindowへフォーカス
        QtCore.QTimer.singleShot(
            0,
            self.setFocus
        )

        #self.resize(1200, 800)
        self.showMaximized()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def select_direct_save_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "保存先フォルダを選択"
        )

        if not directory:
            return

        self.direct_save_line_edit.setText(directory)
        self.direct_save_radio.setChecked(True)

    def get_active_save_directory(self):
        if self.direct_save_radio.isChecked():
            return self.direct_save_line_edit.text().strip()

        return self.registered_save_combo.currentData()

    def check_same_file_name_exists(self):
        if not hasattr(self, "file_name_warning_label"):
            return

        directory_text = self.get_active_save_directory()
        file_name = self.file_name_line_edit.text().strip()

        if not directory_text or not file_name:
            self.file_name_warning_label.setText("")
            return

        extension = ".png" if self.capture_type == "png" else ".mp4"
        if not file_name.lower().endswith(extension):
            file_name += extension

        file_path = Path(directory_text) / file_name

        if file_path.exists():
            self.file_name_warning_label.setText(
                {
                    JAPANESE: "フォルダ内に同じ名前のファイル名があります",
                    KOREAN: "폴더 안에 같은 이름의 파일이 있습니다",
                    ENGLISH: "A file with the same name already exists in this folder.",
                    SIMPLIFIED_CHINESE: "此文件夹中已存在同名文件。",
                    TRADITIONAL_CHINESE: "此資料夾中已存在同名檔案。"
                }[self.main_window.text_language]
            )
        else:
            self.file_name_warning_label.setText("")

    def set_auto_file_name(self):
        directory_text = self.get_active_save_directory()

        if not directory_text:
            return

        directory = Path(directory_text)

        date_text = datetime.now().strftime("%y%m%d")

        number = 1
        extension = ".png" if self.capture_type == "png" else ".mp4"

        while True:
            file_name = f"{date_text}_{number:03d}"
            file_path = directory / f"{file_name}{extension}"

            if not file_path.exists():
                self.file_name_line_edit.setText(file_name)
                return file_name

            number += 1

    def save_recorded_mp4(self):
        if not self.recorded_frames:
            return

        directory_text = self.get_active_save_directory()
        file_name = self.file_name_line_edit.text().strip()

        if not directory_text :
            return
        if not file_name:
            file_name = self.set_auto_file_name()

        QtWidgets.QApplication.processEvents()

        directory = Path(directory_text)
        directory.mkdir(parents=True, exist_ok=True)

        if not file_name.lower().endswith(".mp4"):
            file_name += ".mp4"

        save_path = directory / file_name

        resize_percent = self.save_resize_slider.value()
        scale = resize_percent / 100.0

        self.loadingWindow.progress.setValue(5)

        save_frames = []
        frame_count = len(self.recorded_frames)

        for index, frame in enumerate(self.recorded_frames):
            if resize_percent != 100:
                width = max(2, int(frame.width * scale))
                height = max(2, int(frame.height * scale))
            else:
                width = frame.width
                height = frame.height

            # H.264 / yuv420p用に偶数サイズへ統一
            width = max(2, width - (width % 2))
            height = max(2, height - (height % 2))

            if frame.size != (width, height):
                save_frame = frame.resize(
                    (width, height),
                    Image.Resampling.LANCZOS
                )
            else:
                save_frame = frame

            if save_frame.mode != "RGB":
                save_frame = save_frame.convert("RGB")

            save_frames.append(save_frame)

            progress_value = 5 + int(
                5 * ((index + 1) / frame_count)
            )
            self.loadingWindow.progress.setValue(progress_value)
            QtWidgets.QApplication.processEvents()

        # 全フレームを先頭フレームと同じサイズへ統一
        output_size = save_frames[0].size
        normalized_frames = []

        for frame in save_frames:
            if frame.size != output_size:
                frame = frame.resize(
                    output_size,
                    Image.Resampling.LANCZOS
                )

            if frame.mode != "RGB":
                frame = frame.convert("RGB")

            normalized_frames.append(frame)

        # MP4保存は疑似進捗ではなく、
        # 実際にffmpegへ送信したフレーム数で進捗を更新する。
        self.stop_fake_save_progress(
            set_complete=False
        )
        self.loadingWindow.progress.setValue(10)

        self.mp4_save_thread = Mp4SaveThread(
            save_path=save_path,
            save_frames=normalized_frames,
            fps=self.fps,
            parent=self
        )

        self.mp4_save_thread.saveProgress.connect(
            self.loadingWindow.progress.setValue
        )

        self.mp4_save_thread.saveFinished.connect(
            self.on_mp4_encode_finished
        )

        self.mp4_save_thread.saveFailed.connect(
            self.on_mp4_save_failed
        )

        self.mp4_save_thread.start()

    def on_mp4_encode_finished(self):
        # MP4はwriter.close()まで完了済み。
        # ここからは一覧表示用GIFの作成工程へ移る。
        self.loadingWindow.progress.setValue(90)

        if hasattr(self, "mp4_save_thread") and self.mp4_save_thread is not None:
            self.mp4_save_thread.deleteLater()
            self.mp4_save_thread = None

        self._mp4_saved_before_gif = True
        self.save_recorded_gif()

    def save_recorded_gif(self):
        if not self.recorded_frames:
            return

        directory_text = self.get_active_save_directory()
        file_name = self.file_name_line_edit.text().strip()

        if not directory_text or not file_name:
            return

        QtWidgets.QApplication.processEvents()

        directory = Path(directory_text)
        directory.mkdir(parents=True, exist_ok=True)

        if not file_name.lower().endswith(".gif"):
            file_name += ".gif"

        save_path = directory / IMAGE_DIRECTORY_SHOW / file_name

        current_frame_count = len(self.recorded_frames)
        total_seconds = current_frame_count / max(float(self.fps), 0.001)
        original_frame_count = getattr(self, "original_frame_count", current_frame_count)
        is_frame_deleted = current_frame_count != original_frame_count

        # サムネ専用保存ボタンの場合は、編集内容の先頭3秒だけをGIFにする。
        # MP4自体は通常通り編集後の全フレームを保存する。
        if self.gif_thumbnail_seconds is not None:
            max_frame_count = int(round(float(self.fps) * self.gif_thumbnail_seconds))
            source_frames = self.recorded_frames[:max_frame_count]
        elif total_seconds > 30 and not is_frame_deleted:
            # 通常保存で30秒超、かつフレーム削除なしの場合は先頭10秒をGIFにする。
            max_frame_count = int(round(float(self.fps) * 10))
            source_frames = self.recorded_frames[:max_frame_count]
        else:
            source_frames = self.recorded_frames

        # 60fps以上は30fpsへ
        if self.fps >= 60:
            gif_fps = 30
            source_frames = source_frames[::2]
        else:
            gif_fps = self.fps

        duration = int(round(1000 / gif_fps))

        is_after_mp4_save = getattr(
            self,
            "_mp4_saved_before_gif",
            False
        )

        if is_after_mp4_save:
            progress_start = 90
            progress_range = 5
        else:
            progress_start = 5
            progress_range = 10

        self.loadingWindow.progress.setValue(progress_start)

        save_frames = []
        frame_count = len(source_frames)

        for index, frame in enumerate(source_frames):
            scale = self.main_window.show_image_height / frame.height
            target_width = max(1, int(round(frame.width * scale)))

            resized_frame = frame.resize(
                (target_width, self.main_window.show_image_height),
                Image.Resampling.LANCZOS
            )

            save_frames.append(resized_frame)

            progress_value = progress_start + int(
                progress_range * ((index + 1) / frame_count)
            )
            self.loadingWindow.progress.setValue(progress_value)
            QtWidgets.QApplication.processEvents()

        self.start_fake_save_progress(
            start_value=95 if is_after_mp4_save else 15
        )

        self.gif_save_thread = GifSaveThread(
            save_path=save_path,
            save_frames=save_frames,
            duration=duration,
            parent=self
        )

        self.gif_save_thread.saveFinished.connect(
            self.on_gif_save_finished
        )

        self.gif_save_thread.saveFailed.connect(
            self.on_gif_save_failed
        )

        self.gif_save_thread.start()

    def on_gif_save_finished(self):
        self.stop_fake_save_progress()
        self.loadingWindow.hide()
        self.main_window.reload_show_image_next_wrapper()

        if hasattr(self, "gif_save_thread"):
            self.gif_save_thread.deleteLater()
            self.gif_save_thread = None

        self.gif_thumbnail_seconds = None
        self._mp4_saved_before_gif = False
        self.main_window.save_shoot_process_edit_window = None

        for pick in self.main_window.gifshootWindow_edit_list:
            if hasattr(pick, "save_gif_button") and pick.save_gif_button is not None:
                pick.save_gif_button.setEnabled(True)
                pick.save_gif_button.setStyleSheet(Utility_ButtonStyles.standard())
                pick.save_gif_button.setText(
                    {
                        JAPANESE: "編集内容を保存" if pick.capture_type == CAPTURE_TYPE_MP4 else "保存",
                        KOREAN: "편집 내용 저장" if pick.capture_type == CAPTURE_TYPE_MP4 else "저장",
                        ENGLISH: "Save Edited Content" if pick.capture_type == CAPTURE_TYPE_MP4 else "Save PNG",
                        SIMPLIFIED_CHINESE: "保存编辑内容" if pick.capture_type == CAPTURE_TYPE_MP4 else "保存PNG",
                        TRADITIONAL_CHINESE: "儲存編輯內容" if pick.capture_type == CAPTURE_TYPE_MP4 else "儲存PNG"
                    }[self.main_window.text_language]
                )

            if hasattr(pick, "save_thumbnail_5sec_button") and pick.save_thumbnail_5sec_button is not None:
                pick.save_thumbnail_5sec_button.setEnabled(True)
                pick.save_thumbnail_5sec_button.setStyleSheet(Utility_ButtonStyles.standard())
                pick.save_thumbnail_5sec_button.setText(
                    {
                        JAPANESE: "サムネを再作成する為最初の1秒だけ保存",
                        KOREAN: "썸네일을 다시 생성하기 위해 처음 1초만 저장",
                        ENGLISH: "Save Only the First 1 Second to Recreate the Thumbnail",
                        SIMPLIFIED_CHINESE: "仅保存最初1秒以重新创建缩略图",
                        TRADITIONAL_CHINESE: "僅儲存最初1秒以重新建立縮圖"
                    }[self.main_window.text_language]
                )

        self.close()

    def on_gif_save_failed(self, error_message):
        self.stop_fake_save_progress()
        self.loadingWindow.hide()

        if hasattr(self, "gif_save_thread"):
            self.gif_save_thread.deleteLater()
            self.gif_save_thread = None

        self.gif_thumbnail_seconds = None
        self._mp4_saved_before_gif = False
        self.main_window.save_shoot_process_edit_window = None

        if hasattr(self, "save_gif_button") and self.save_gif_button is not None:
            self.save_gif_button.setEnabled(True)
            self.save_gif_button.setStyleSheet(Utility_ButtonStyles.standard())
            self.save_gif_button.setText(
                {
                    JAPANESE: "編集内容を保存" if self.capture_type == CAPTURE_TYPE_MP4 else "保存",
                    KOREAN: "편집 내용 저장" if self.capture_type == CAPTURE_TYPE_MP4 else "저장",
                    ENGLISH: "Save Edited Content" if self.capture_type == CAPTURE_TYPE_MP4 else "Save PNG",
                    SIMPLIFIED_CHINESE: "保存编辑内容" if self.capture_type == CAPTURE_TYPE_MP4 else "保存PNG",
                    TRADITIONAL_CHINESE: "儲存編輯內容" if self.capture_type == CAPTURE_TYPE_MP4 else "儲存PNG"
                }[self.main_window.text_language]
            )

        if hasattr(self, "save_thumbnail_5sec_button") and self.save_thumbnail_5sec_button is not None:
            self.save_thumbnail_5sec_button.setEnabled(True)
            self.save_thumbnail_5sec_button.setStyleSheet(Utility_ButtonStyles.standard())
            self.save_thumbnail_5sec_button.setText(
                {
                    JAPANESE: "サムネを再作成する為最初の1秒だけ保存",
                    KOREAN: "썸네일을 다시 생성하기 위해 처음 1초만 저장",
                    ENGLISH: "Save Only the First 1 Second to Recreate the Thumbnail",
                    SIMPLIFIED_CHINESE: "仅保存最初1秒以重新创建缩略图",
                    TRADITIONAL_CHINESE: "僅儲存最初1秒以重新建立縮圖"
                }[self.main_window.text_language]
            )

        QtWidgets.QMessageBox.critical(self, "GIF Save Error", error_message)

    def start_fake_save_progress(self, start_value=10):
        # 既存Timerが残っている場合は必ず停止してから作り直す。
        self.stop_fake_save_progress(
            set_complete=False
        )

        self.fake_save_progress_value = float(start_value)
        self.loadingWindow.progress.setValue(
            int(self.fake_save_progress_value)
        )

        self.fake_save_progress_timer = QtCore.QTimer(self)
        self.fake_save_progress_timer.setInterval(100)

        self.fake_save_progress_timer.timeout.connect(
            self.update_fake_save_progress
        )

        self.fake_save_progress_timer.start()

    def update_fake_save_progress(self):
        if self.fake_save_progress_value >= 98:
            return

        # 最初は速く、後半になるほど遅くする
        if self.fake_save_progress_value < 40:
            increment = 1
        elif self.fake_save_progress_value < 75:
            increment = 0.5
        else:
            increment = 0.125

        self.fake_save_progress_value = min(
            98,
            self.fake_save_progress_value + increment
        )
        self.loadingWindow.progress.setValue(
            int(self.fake_save_progress_value)
        )

    def stop_fake_save_progress(self, set_complete=True):
        timer = getattr(
            self,
            "fake_save_progress_timer",
            None
        )

        if timer is not None:
            timer.stop()
            try:
                timer.timeout.disconnect(
                    self.update_fake_save_progress
                )
            except (TypeError, RuntimeError):
                pass
            timer.deleteLater()
            self.fake_save_progress_timer = None

        if set_complete:
            self.loadingWindow.progress.setValue(100)

    def on_mp4_save_finished(self):
        self.stop_fake_save_progress()

        self.loadingWindow.hide()

        self.main_window.reload_show_image_next_wrapper()

        if hasattr(self, "mp4_save_thread"):
            self.mp4_save_thread.deleteLater()
            self.mp4_save_thread = None

        for i, pick in enumerate(self.main_window.gifshootWindow_edit_list):
            pick.save_gif_button.clicked.connect(pick.save_recorded_file)
            pick.save_gif_button.setText(
                {
                    JAPANESE: "保存",
                    KOREAN: "저장",
                    ENGLISH: "Save",
                    SIMPLIFIED_CHINESE: "保存",
                    TRADITIONAL_CHINESE: "儲存"
                }[self.main_window.text_language]
            )

        self.close()

    def on_mp4_save_failed(self, error_message):
        self.stop_fake_save_progress()
        self.loadingWindow.hide()

        if hasattr(self, "mp4_save_thread"):
            self.mp4_save_thread.deleteLater()
            self.mp4_save_thread = None

        self.gif_thumbnail_seconds = None
        self.main_window.save_shoot_process_edit_window = None

        if hasattr(self, "save_gif_button") and self.save_gif_button is not None:
            self.save_gif_button.setEnabled(True)
            self.save_gif_button.setStyleSheet(Utility_ButtonStyles.standard())
            self.save_gif_button.setText(
                {
                    JAPANESE: "編集内容を保存" if self.capture_type == CAPTURE_TYPE_MP4 else "保存",
                    KOREAN: "편집 내용 저장" if self.capture_type == CAPTURE_TYPE_MP4 else "저장",
                    ENGLISH: "Save Edited Content" if self.capture_type == CAPTURE_TYPE_MP4 else "Save PNG",
                    SIMPLIFIED_CHINESE: "保存编辑内容" if self.capture_type == CAPTURE_TYPE_MP4 else "保存PNG",
                    TRADITIONAL_CHINESE: "儲存編輯內容" if self.capture_type == CAPTURE_TYPE_MP4 else "儲存PNG"
                }[self.main_window.text_language]
            )

        if hasattr(self, "save_thumbnail_5sec_button") and self.save_thumbnail_5sec_button is not None:
            self.save_thumbnail_5sec_button.setEnabled(True)
            self.save_thumbnail_5sec_button.setStyleSheet(Utility_ButtonStyles.standard())
            self.save_thumbnail_5sec_button.setText(
                {
                    JAPANESE: "サムネを再作成する為最初の1秒だけ保存",
                    KOREAN: "썸네일을 다시 생성하기 위해 처음 1초만 저장",
                    ENGLISH: "Save Only the First 1 Second to Recreate the Thumbnail",
                    SIMPLIFIED_CHINESE: "仅保存最初1秒以重新创建缩略图",
                    TRADITIONAL_CHINESE: "僅儲存最初1秒以重新建立縮圖"
                }[self.main_window.text_language]
            )

        QtWidgets.QMessageBox.critical(self, "MP4 Save Error", error_message)

    def rebuild_thumbnails(self):
        while self.thumbnail_layout.count():
            item = self.thumbnail_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.thumbnail_buttons = []
        frame_count = len(self.recorded_frames)

        if frame_count == 0:
            return

        for index, frame in enumerate(self.recorded_frames):
            button = FrameThumbnailButton(index, frame, self.fps)

            button.clickedIndex.connect(self.select_frame)
            button.draggedIndex.connect(self.preview_dragged_frame)
            button.rightClickedIndex.connect(self.set_overlay_frame)
            button.middleClickedIndex.connect(self.clear_overlay_frame)

            button.set_overlay(index == self.overlay_frame_index)
            button.set_selected(index in self.selected_frame_indexes)
            button.set_current(index == self.current_frame_index)

            self.thumbnail_buttons.append(button)
            self.thumbnail_layout.addWidget(button)

            if hasattr(self, "loadingWindow") and self.loadingWindow.isVisible():
                progress = int(
                    ((index + 1) / frame_count) * 95
                )

                self.loadingWindow.progress.setValue(progress)

        self.thumbnail_layout.addStretch()

    def update_thumbnail_states(self):
        if not hasattr(self, "thumbnail_buttons"):
            return

        for index, button in enumerate(self.thumbnail_buttons):
            button.set_current(index == self.current_frame_index)
            button.set_selected(index in self.selected_frame_indexes)
            button.set_overlay(index == self.overlay_frame_index)

    def preview_dragged_frame(self, index):
        if index < 0 or index >= len(self.recorded_frames):
            return

        if index == self.current_frame_index:
            return

        self.current_frame_index = index
        self.selected_frame_indexes = {index}
        self.shift_anchor = index

        self.update_thumbnail_states()
        self.show_current_frame()

    def select_frame(self, index):
        if index < 0 or index >= len(self.recorded_frames):
            return

        modifiers = QtWidgets.QApplication.keyboardModifiers()

        if modifiers & QtCore.Qt.ShiftModifier:
            if not hasattr(self, "shift_anchor"):
                self.shift_anchor = self.current_frame_index

            start = min(self.shift_anchor, index)
            end = max(self.shift_anchor, index)

            self.selected_frame_indexes = set(range(start, end + 1))
            self.current_frame_index = index
        else:
            self.current_frame_index = index
            self.selected_frame_indexes = {index}
            self.shift_anchor = index

        self.update_thumbnail_states()
        self.show_current_frame()
        self.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)

        if (
            self.editor_mode
            and hasattr(self, "preview_label")
            and self.recorded_frames
        ):
            QtCore.QTimer.singleShot(
                0,
                self.show_current_frame
            )

    def show_current_frame(self):
        if not self.recorded_frames:
            self.preview_label.clear()
            return

        base_image = ImageQt.ImageQt(
            self.recorded_frames[
                self.current_frame_index
            ]
        ).convertToFormat(
            QtGui.QImage.Format_ARGB32
        )

        if self.overlay_frame_index is not None:
            overlay_image = ImageQt.ImageQt(
                self.recorded_frames[
                    self.overlay_frame_index
                ]
            ).convertToFormat(
                QtGui.QImage.Format_ARGB32
            )

            composed = QtGui.QImage(
                base_image.size(),
                QtGui.QImage.Format_ARGB32
            )

            composed.fill(
                QtCore.Qt.transparent
            )

            painter = QtGui.QPainter(
                composed
            )

            painter.drawImage(
                0,
                0,
                base_image
            )

            painter.setOpacity(
                self.overlay_opacity / 100
            )

            painter.drawImage(
                0,
                0,
                overlay_image
            )

            painter.end()

            pixmap = QtGui.QPixmap.fromImage(
                composed
            )

        else:
            pixmap = QtGui.QPixmap.fromImage(
                base_image
            )

        # =========================================================
        # 現在のpreview_labelサイズに収める
        # =========================================================

        target_size = self.preview_label.contentsRect().size()

        if (
            target_size.width() > 1
            and target_size.height() > 1
        ):
            original_size = pixmap.size()

            target_width = min(
                target_size.width(),
                original_size.width()
            )

            target_height = min(
                target_size.height(),
                original_size.height()
            )

            pixmap = pixmap.scaled(
                QtCore.QSize(
                    target_width,
                    target_height
                ),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation
            )

        self.preview_label.setPixmap(
            pixmap
        )

        if hasattr(
            self,
            "preview_info_label"
        ):
            current_second = (
                self.current_frame_index
                / self.fps
            )

            max_second = (
                (len(self.recorded_frames) - 1)
                / self.fps
            )

            self.preview_info_label.setText(
                f"{self.fps} FPS    "
                f"{self.current_frame_index} / "
                f"{len(self.recorded_frames) - 1}    "
                f"{current_second:.2f} / "
                f"{max_second:.2f}s"
            )

        if hasattr(
            self,
            "resize_compare_bar"
        ):
            self.resize_compare_bar.set_resize_info(
                pixmap.height(),
                self.save_resize_percent
            )

    def move_to_first_frame(self):
        if not self.recorded_frames:
            return

        self.current_frame_index = 0
        self.selected_frame_indexes = {0}

        self.update_thumbnail_states()
        self.show_current_frame()
        self.scroll_to_current_thumbnail()

        self.shift_anchor = 0

    def toggle_play(self):
        if not self.recorded_frames:
            return

        if self.play_timer.isActive():
            self.play_timer.stop()

            if hasattr(self, "editor_play_button"):
                self.editor_play_button.setText("▶")
        else:
            self.play_start_time = time.perf_counter()
            self.play_start_index = self.current_frame_index
            self.play_timer.start(10)

            if hasattr(self, "editor_play_button"):
                self.editor_play_button.setText("Ⅱ")

    def smooth_scroll_to_current_thumbnail(self):
        if not hasattr(self, "thumbnail_buttons"):
            return

        if self.current_frame_index >= len(self.thumbnail_buttons):
            return

        button = self.thumbnail_buttons[self.current_frame_index]
        bar = self.thumbnail_area.horizontalScrollBar()

        target_x = (
            button.x()
            - self.thumbnail_area.viewport().width()
            + button.width()
            + 20
        )

        target_x = max(bar.minimum(), min(target_x, bar.maximum()))

        animation = QtCore.QPropertyAnimation(bar, b"value", self)
        animation.setDuration(80)
        animation.setStartValue(bar.value())
        animation.setEndValue(target_x)
        animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        animation.start(QtCore.QAbstractAnimation.DeleteWhenStopped)

        self.thumbnail_scroll_animation = animation

    def play_next_frame(self):
        if not self.recorded_frames:
            self.play_timer.stop()
            return

        old_index = self.current_frame_index

        elapsed = time.perf_counter() - self.play_start_time
        frame_offset = int(elapsed * self.fps)

        self.current_frame_index = (
            self.play_start_index + frame_offset
        ) % len(self.recorded_frames)

        if self.current_frame_index == old_index:
            return

        self.selected_frame_indexes = {self.current_frame_index}

        if hasattr(self, "thumbnail_buttons"):
            if old_index < len(self.thumbnail_buttons):
                self.thumbnail_buttons[old_index].set_current(False)
                self.thumbnail_buttons[old_index].set_selected(False)

            if self.current_frame_index < len(self.thumbnail_buttons):
                self.thumbnail_buttons[self.current_frame_index].set_current(True)
                self.thumbnail_buttons[self.current_frame_index].set_selected(True)

        self.show_current_frame()
        self.smooth_scroll_to_current_thumbnail()

    def select_previous_with_shift(self):
        if not self.recorded_frames:
            return

        if not hasattr(self, "shift_anchor"):
            self.shift_anchor = self.current_frame_index

        self.current_frame_index = max(
            self.current_frame_index - 1,
            0
        )

        start = min(self.shift_anchor, self.current_frame_index)
        end = max(self.shift_anchor, self.current_frame_index)

        self.selected_frame_indexes = set(range(start, end + 1))

        self.update_thumbnail_states()
        self.show_current_frame()
        self.scroll_to_current_thumbnail()

    def select_next_with_shift(self):
        if not self.recorded_frames:
            return

        if not hasattr(self, "shift_anchor"):
            self.shift_anchor = self.current_frame_index

        self.current_frame_index = min(
            self.current_frame_index + 1,
            len(self.recorded_frames) - 1
        )

        start = min(self.shift_anchor, self.current_frame_index)
        end = max(self.shift_anchor, self.current_frame_index)

        self.selected_frame_indexes = set(range(start, end + 1))

        self.update_thumbnail_states()
        self.show_current_frame()
        self.scroll_to_current_thumbnail()

    def delete_selected_frames(self):
        if not self.selected_frame_indexes:
            return

        self.loadingWindow.show()
        self.loadingWindow.progress.setValue(0)

        QtCore.QTimer.singleShot(
            100,
            self.delete_selected_frames_wrapper
        )


    def delete_selected_frames_wrapper(self):
        indexes = sorted(
            self.selected_frame_indexes
        )

        deleted = [
            (
                index,
                self.recorded_frames[index]
            )
            for index in indexes
        ]

        self.delete_undo_stack.append(
            deleted
        )

        self.loadingWindow.progress.setValue(20)

        for index in reversed(indexes):
            del self.recorded_frames[index]

        self.selected_frame_indexes.clear()

        if self.recorded_frames:
            self.current_frame_index = min(
                indexes[0],
                len(self.recorded_frames) - 1
            )

            self.selected_frame_indexes = {
                self.current_frame_index
            }

        else:
            self.current_frame_index = 0

        self.loadingWindow.progress.setValue(50)

        self.rebuild_thumbnails()

        self.loadingWindow.progress.setValue(90)

        self.show_current_frame()

        self.loadingWindow.progress.setValue(100)
        self.loadingWindow.hide()

    def undo_delete_frames(self):
        if not self.delete_undo_stack:
            return

        deleted = self.delete_undo_stack.pop()

        for index, frame in deleted:
            self.recorded_frames.insert(index, frame)

        self.selected_frame_indexes = {
            index for index, _ in deleted
        }

        self.current_frame_index = deleted[0][0]

        self.rebuild_thumbnails()
        self.show_current_frame()

    def start_record(self):
        if self.recording:
            return

        self.capture_type = CAPTURE_TYPE_MP4
        self.paused = False
        if self.recording:
            return

        self.recording = True
        self.elapsed_second = 0.0
        self.record_start_time = time.perf_counter()
        self.pause_elapsed = 0.0
        self.pause_start_time = None

        self.control_bar.set_elapsed_time(0.0)
        self.control_bar.set_frame_count(0)
        self.control_bar.set_recording(True)
        self.capture_border.set_recording(True)

        capture_rect = self.capture_rect()

        self.recorder_thread = GifRecorderThread(
            capture_rect=capture_rect,
            fps=self.fps,
            parent=self
        )

        self.recorder_thread.finishedRecording.connect(
            self.on_recording_finished
        )

        self.recorder_thread.frameCaptured.connect(
            self.control_bar.set_frame_count
        )

        self.recorder_thread.captureFailed.connect(
            self.on_capture_failed
        )

        self.recorder_thread.start()

        self.timer.start(10)

        self.recordStarted.emit(capture_rect)

    def on_capture_failed(self, error):
        print(
            "Capture error:",
            error
        )

        self.recording = False
        self.paused = False
        self.timer.stop()

        if self.control_bar is not None:
            self.control_bar.set_recording(False)
            self.control_bar.pause_button.setText("Ⅱ Pause")

        if self.capture_border is not None:
            self.capture_border.set_recording(False)

        self.recordStopped.emit()

    def stop_record(self):
        if not self.recording:
            return

        self.recording = False

        self.timer.stop()

        self.control_bar.set_recording(False)
        self.capture_border.set_recording(False)

        if self.recorder_thread is not None:
            self.recorder_thread.stop()

        self.paused = False
        self.control_bar.pause_button.setText("Ⅱ Pause")

        self.recordStopped.emit()

    def on_recording_finished(self, frames):
        self.recorder_thread = None

        if not frames:
            return

        self.recorded_frames = frames
        self.current_frame_index = 0
        self.selected_frame_indexes.clear()
        self.delete_undo_stack.clear()

        self.hide()

        Utility_Window_Setting.save_window_pos_json(
            self,
            self.main_window.window_setting_dict,
            GIFSHOOT_WINDOW_DICT,
            True
        )

        editor = GifShootWindow(
            self.main_window,
            editor_mode=True,
        )

        editor.setWindowTitle(
            GIFSHOOT_WINDOW_DICT[
                SHOW_TITLE
            ][
                self.main_window.text_language
            ]
        )

        editor.recorded_frames = frames
        editor.original_frame_count = len(frames)
        editor.fps = self.fps
        editor.current_frame_index = 0
        editor.selected_frame_indexes = {0}
        editor.delete_undo_stack.clear()
        editor.overlay_frame_index = None

        if editor not in self.main_window.gifshootWindow_edit_list:
            self.main_window.gifshootWindow_edit_list.append(
                editor
            )

        # ==========================================
        # LoadingWindow表示
        # ==========================================

        editor.loadingWindow.progress.setValue(0)

        editor.loadingWindow.show()
        editor.loadingWindow.raise_()

        # ==========================================
        # 編集画面作成
        # この中でサムネイル生成が行われる
        # ==========================================

        editor.show_frame_editor()

        # ==========================================
        # 編集Window位置・サイズ復元
        # ==========================================

        try:
            setting_json_dict = (
                self.main_window
                .window_setting_dict[
                    WINDOW_INFO_KEY
                ]
            )

            editor.move(
                setting_json_dict[
                    GIFEDIT_WINDOW_DICT[
                        PROGRAM_NAME
                    ]
                ][
                    WINDOW_POS_KEY
                ][
                    WINDOW_POS_X_KEY
                ],
                setting_json_dict[
                    GIFEDIT_WINDOW_DICT[
                        PROGRAM_NAME
                    ]
                ][
                    WINDOW_POS_KEY
                ][
                    WINDOW_POS_Y_KEY
                ] - 30
            )

            editor.resize(
                setting_json_dict[
                    GIFEDIT_WINDOW_DICT[
                        PROGRAM_NAME
                    ]
                ][
                    WINDOW_POS_KEY
                ][
                    WINDOW_WIDTH_KEY
                ],
                setting_json_dict[
                    GIFEDIT_WINDOW_DICT[
                        PROGRAM_NAME
                    ]
                ][
                    WINDOW_POS_KEY
                ][
                    WINDOW_HEIGHT_KEY
                ]
            )

        except Exception:
            pass

        self.editor_window = editor
        editor.record_window = self

        # ==========================================
        # 完了
        # ==========================================

        editor.loadingWindow.progress.setValue(100)
        editor.loadingWindow.hide()

    def on_timeout(self):
        if self.paused:
            return

        self.elapsed_second = (
            time.perf_counter()
            - self.record_start_time
            - self.pause_elapsed
        )

        self.control_bar.set_elapsed_time(
            self.elapsed_second
        )

    #02
    def capture_rect(self):
        top_left = self.capture_frame.mapToGlobal(QtCore.QPoint(0, 0))

        screen = QtGui.QGuiApplication.screenAt(top_left)
        if screen is None:
            screen = self.screen()

        dpr = screen.devicePixelRatio()
        screen_geo = screen.geometry()

        left = screen_geo.x() + int((top_left.x() - screen_geo.x()) * dpr)
        top = screen_geo.y() + int((top_left.y() - screen_geo.y()) * dpr)

        width = int(self.capture_frame.width() * dpr)
        height = int(self.capture_frame.height() * dpr)

        # 左上だけ1px内側に寄せる
        left += 1
        top += 1
        width -= 1
        height -= 1

        return {
            "left": left,
            "top": top,
            "width": max(1, width),
            "height": max(1, height),
        }

    def get_resize_edge(self, pos: QtCore.QPoint):
        edge = self.EDGE_NONE

        if pos.x() <= self.RESIZE_MARGIN:
            edge |= self.EDGE_LEFT

        elif pos.x() >= self.width() - self.RESIZE_MARGIN:
            edge |= self.EDGE_RIGHT

        if pos.y() <= self.RESIZE_MARGIN:
            edge |= self.EDGE_TOP

        elif pos.y() >= self.height() - self.RESIZE_MARGIN:
            edge |= self.EDGE_BOTTOM

        return edge

    def update_cursor(self, edge):
        if self.recording or self.paused:
            self.unsetCursor()
            return
        if edge in (self.EDGE_LEFT, self.EDGE_RIGHT):
            self.setCursor(QtCore.Qt.SizeHorCursor)

        elif edge in (self.EDGE_TOP, self.EDGE_BOTTOM):
            self.setCursor(QtCore.Qt.SizeVerCursor)

        elif edge in (
            self.EDGE_TOP | self.EDGE_LEFT,
            self.EDGE_BOTTOM | self.EDGE_RIGHT
        ):
            self.setCursor(QtCore.Qt.SizeFDiagCursor)

        elif edge in (
            self.EDGE_TOP | self.EDGE_RIGHT,
            self.EDGE_BOTTOM | self.EDGE_LEFT
        ):
            self.setCursor(QtCore.Qt.SizeBDiagCursor)

        else:
            self.setCursor(QtCore.Qt.ArrowCursor)

    def is_title_bar(self, pos):
        if self.title_bar is None:
            return False

        if pos.y() > self.title_bar.height():
            return False

        child = self.childAt(pos)

        if isinstance(child, QtWidgets.QPushButton):
            return False

        return True

    def mousePressEvent(self, event):
        if self.editor_mode:
            event.ignore()
            return

        if self.recording or self.paused:
            self.drag_offset = None
            self.resizing = False
            self.resize_edge = self.EDGE_NONE
            return

        if event.button() != QtCore.Qt.LeftButton:
            return

        pos = event.position().toPoint()

        self.resize_edge = self.get_resize_edge(pos)

        if self.resize_edge != self.EDGE_NONE:
            self.resizing = True
            self.resize_start_geometry = self.geometry()
            self.resize_start_global = event.globalPosition().toPoint()
            return

        if self.is_title_bar(pos):
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.editor_mode:
            event.ignore()
            return

        pos = event.position().toPoint()
        global_pos = event.globalPosition().toPoint()

        if self.resizing:
            delta = global_pos - self.resize_start_global
            geo = QtCore.QRect(self.resize_start_geometry)

            min_w = self.minimumWidth()
            min_h = self.minimumHeight()

            if self.resize_edge & self.EDGE_LEFT:
                new_left = geo.left() + delta.x()
                max_left = geo.right() - min_w + 1
                geo.setLeft(min(new_left, max_left))

            if self.resize_edge & self.EDGE_RIGHT:
                new_right = geo.right() + delta.x()
                min_right = geo.left() + min_w - 1
                geo.setRight(max(new_right, min_right))

            if self.resize_edge & self.EDGE_TOP:
                new_top = geo.top() + delta.y()
                max_top = geo.bottom() - min_h + 1
                geo.setTop(min(new_top, max_top))

            if self.resize_edge & self.EDGE_BOTTOM:
                new_bottom = geo.bottom() + delta.y()
                min_bottom = geo.top() + min_h - 1
                geo.setBottom(max(new_bottom, min_bottom))

            self.title_bar.preset_combo.setCurrentIndex(-1)
            self.setGeometry(geo)
            self.update_title_bar_capture_size()
            self.update_recorder_capture_rect()
            return

        if (
            self.drag_offset is not None
            and event.buttons() & QtCore.Qt.LeftButton
        ):
            self.move(global_pos - self.drag_offset)
            self.update_recorder_capture_rect()
            return

        self.update_cursor(
            self.get_resize_edge(pos)
        )

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):

        if self.editor_mode:
            event.ignore()
            return

        self.drag_offset = None
        self.resizing = False
        self.resize_edge = self.EDGE_NONE

        try:
            self.releaseMouse()

        except RuntimeError:
            pass

        self.unsetCursor()

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self.resizing:
            self.unsetCursor()

        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if hasattr(self, "editor_widget") and self.editor_widget.isVisible():

            if event.key() == QtCore.Qt.Key_Space:
                self.toggle_play()
                return

            if (
                event.key() == QtCore.Qt.Key_Z
                and event.modifiers() & QtCore.Qt.ControlModifier
            ):
                self.undo_delete_frames()
                return

            if event.key() == QtCore.Qt.Key_Delete:
                self.delete_selected_frames()
                return

            if (
                event.key() == QtCore.Qt.Key_Left
                and event.modifiers() & QtCore.Qt.ShiftModifier
            ):
                self.select_previous_with_shift()
                return

            if event.key() == QtCore.Qt.Key_Left:
                self.move_frame_selection(-1)
                return

            if (
                event.key() == QtCore.Qt.Key_Right
                and event.modifiers() & QtCore.Qt.ShiftModifier
            ):
                self.select_next_with_shift()
                return

            if event.key() == QtCore.Qt.Key_Right:
                self.move_frame_selection(1)
                return

            if (
                event.key() == QtCore.Qt.Key_D
                and event.modifiers() & QtCore.Qt.ShiftModifier
            ):
                self.select_previous_with_shift()
                return

            if (
                event.key() == QtCore.Qt.Key_F
                and event.modifiers() & QtCore.Qt.ShiftModifier
            ):
                self.select_next_with_shift()
                return

            if event.key() == QtCore.Qt.Key_D:
                self.move_frame_selection(-1)
                return

            if event.key() == QtCore.Qt.Key_F:
                self.move_frame_selection(1)
                return

        # 既存処理
        if event.key() == QtCore.Qt.Key_Escape:
            if self.recording:
                self.stop_record()
            self.close()
            return

        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.toggle_record()
            return

        super().keyPressEvent(event)
