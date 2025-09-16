import sys
import os
import datetime
from functools import partial
from typing import List, Optional

import serial
import serial.tools.list_ports as list_ports
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SerialThread(QThread):
    """后台线程持续读取串口数据。"""

    data_received = pyqtSignal(bytes)

    def __init__(self, ser: serial.Serial):
        super().__init__()
        self.ser = ser
        self._running = True

    def run(self) -> None:
        while self._running and self.ser.is_open:
            try:
                if self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting)
                    self.data_received.emit(data)
                self.msleep(10)
            except Exception:
                break

    def stop(self) -> None:
        self._running = False
        self.wait(1000)


class SerialTool(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("串口调试助手 (PyQt5)")

        self.ser: Optional[serial.Serial] = None
        self.thread: Optional[SerialThread] = None
        self.log_enabled = False
        self.log_path = ""
        self.quick_command_rows: List[QLineEdit] = []

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        # 顶部串口设置区域
        top_layout = QHBoxLayout()
        self.port_box = QComboBox()
        self.baud_box = QComboBox()
        for baud in ["9600", "19200", "38400", "57600", "115200", "230400", "460800"]:
            self.baud_box.addItem(baud)
        self.refresh_ports()

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_ports)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.toggle_connection)

        top_layout.addWidget(QLabel("串口:"))
        top_layout.addWidget(self.port_box)
        top_layout.addWidget(QLabel("波特率:"))
        top_layout.addWidget(self.baud_box)
        top_layout.addWidget(refresh_btn)
        top_layout.addWidget(self.connect_btn)
        top_layout.addStretch(1)

        main_layout.addLayout(top_layout)

        # Tab 组件
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._init_monitor_tab()
        self._init_quick_send_tab()

    def _init_monitor_tab(self) -> None:
        monitor_widget = QWidget()
        layout = QVBoxLayout()
        monitor_widget.setLayout(layout)

        # 接收区
        self.recv_text = QTextEdit()
        self.recv_text.setReadOnly(True)
        layout.addWidget(self.recv_text)

        # 发送区
        send_layout = QHBoxLayout()
        self.send_edit = QTextEdit()
        self.send_edit.setPlaceholderText("输入待发送的文本（支持多行）")
        self.send_edit.setFixedHeight(80)

        send_button_column = QVBoxLayout()
        send_btn = QPushButton("发送")
        send_btn.clicked.connect(self.send_data)
        clear_btn = QPushButton("清空接收")
        clear_btn.clicked.connect(self.recv_text.clear)
        send_button_column.addWidget(send_btn)
        send_button_column.addWidget(clear_btn)
        send_button_column.addStretch(1)

        send_layout.addWidget(self.send_edit, 1)
        send_layout.addLayout(send_button_column)

        layout.addLayout(send_layout)

        # 日志控制
        log_layout = QHBoxLayout()
        self.log_check = QCheckBox("记录日志")
        self.log_check.stateChanged.connect(self.toggle_logging)
        choose_log = QPushButton("日志目录")
        choose_log.clicked.connect(self.choose_log_dir)

        log_layout.addWidget(self.log_check)
        log_layout.addWidget(choose_log)
        log_layout.addStretch(1)

        layout.addLayout(log_layout)

        self.tabs.addTab(monitor_widget, "监视")

    def _init_quick_send_tab(self) -> None:
        quick_widget = QWidget()
        layout = QVBoxLayout()
        quick_widget.setLayout(layout)

        description = QLabel("配置多个快捷发送文本，点击对应按钮即可发送。")
        layout.addWidget(description)

        self.quick_grid = QGridLayout()
        layout.addLayout(self.quick_grid)

        button_bar = QHBoxLayout()
        add_btn = QPushButton("添加输入框")
        add_btn.clicked.connect(self.add_quick_command_row)
        button_bar.addWidget(add_btn)
        button_bar.addStretch(1)
        layout.addLayout(button_bar)

        # 初始化 3 个快捷发送框
        for _ in range(3):
            self.add_quick_command_row()

        layout.addStretch(1)
        self.tabs.addTab(quick_widget, "快捷发送")

    # ---------- 串口操作 ----------
    def refresh_ports(self) -> None:
        current = self.port_box.currentText()
        self.port_box.blockSignals(True)
        self.port_box.clear()
        ports = [p.device for p in list_ports.comports()]
        self.port_box.addItems(ports)
        if current and current in ports:
            index = ports.index(current)
            self.port_box.setCurrentIndex(index)
        self.port_box.blockSignals(False)

    def toggle_connection(self) -> None:
        if self.ser and self.ser.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self) -> None:
        try:
            port = self.port_box.currentText()
            if not port:
                self.recv_text.append("[ERROR] 未检测到可用串口")
                return

            baud = int(self.baud_box.currentText())
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.connect_btn.setText("断开")
            self.recv_text.append(f"[INFO] Connected to {port} @ {baud}")
            self.thread = SerialThread(self.ser)
            self.thread.data_received.connect(self.on_data)
            self.thread.start()
        except Exception as e:  # noqa: BLE001
            self.recv_text.append(f"[ERROR] {e}")

    def disconnect_serial(self) -> None:
        if self.thread:
            self.thread.stop()
            self.thread = None
        if self.ser:
            self.ser.close()
            self.ser = None
        self.connect_btn.setText("连接")
        self.recv_text.append("[INFO] Disconnected")

    # ---------- 数据发送/接收 ----------
    def send_data(self) -> None:
        text = self.send_edit.toPlainText().strip()
        if self.ser and self.ser.is_open and text:
            self._write_serial(text)
            self.send_edit.clear()

    def send_quick_command(self, line_edit: QLineEdit) -> None:
        text = line_edit.text().strip()
        if self.ser and self.ser.is_open and text:
            self._write_serial(text)

    def _write_serial(self, text: str) -> None:
        data = text.encode("utf-8")
        self.ser.write(data)
        self.recv_text.append(f"[SEND] {text}")
        self.log(f"[SEND] {text}")

    def on_data(self, data: bytes) -> None:
        text = data.decode("utf-8", errors="replace")
        self.recv_text.append(f"[RECV] {text}")
        self.log(f"[RECV] {text}")

    # ---------- 日志 ----------
    def choose_log_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择日志目录")
        if directory:
            self.log_path = directory

    def toggle_logging(self, state: int) -> None:
        self.log_enabled = state == 2  # Qt.Checked

    def log(self, text: str) -> None:
        if self.log_enabled and self.log_path:
            os.makedirs(self.log_path, exist_ok=True)
            filename = datetime.datetime.now().strftime("%Y-%m-%d.log")
            full_path = os.path.join(self.log_path, filename)
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            with open(full_path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {text}\n")

    # ---------- 快捷发送 ----------
    def add_quick_command_row(self) -> None:
        row = len(self.quick_command_rows)
        line_edit = QLineEdit()
        line_edit.setPlaceholderText(f"输入第 {row + 1} 个命令")
        send_btn = QPushButton("发送")
        send_btn.clicked.connect(partial(self.send_quick_command, line_edit))

        self.quick_grid.addWidget(QLabel(f"命令 {row + 1}:"), row, 0)
        self.quick_grid.addWidget(line_edit, row, 1)
        self.quick_grid.addWidget(send_btn, row, 2)

        self.quick_command_rows.append(line_edit)

    # ---------- 关闭处理 ----------
    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.disconnect_serial()
        event.accept()


def main() -> None:
    app = QApplication(sys.argv)
    tool = SerialTool()
    tool.resize(800, 600)
    tool.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
