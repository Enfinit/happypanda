"""
This file is part of Happypanda.
Happypanda is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 2 of the License, or
any later version.
Happypanda is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys, logging, os, threading
from PyQt5.QtCore import (Qt, QSize, pyqtSignal, QThread, QEvent, QTimer,
						  QObject)
from PyQt5.QtGui import (QPixmap, QIcon, QMouseEvent, QCursor)
from PyQt5.QtWidgets import (QApplication, QMainWindow, QListView,
							 QHBoxLayout, QFrame, QWidget, QVBoxLayout,
							 QLabel, QStackedLayout, QToolBar, QMenuBar,
							 QSizePolicy, QMenu, QAction, QLineEdit,
							 QSplitter, QMessageBox, QFileDialog,
							 QDesktopWidget, QPushButton, QCompleter,
							 QListWidget, QListWidgetItem)
from . import series
from . import gui_constants, misc
from ..database import fetch, seriesdb

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class AppWindow(QMainWindow):
	"The application's main window"
	def __init__(self):
		super().__init__()
		self.center = QWidget()
		self.display = QStackedLayout()
		self.center.setLayout(self.display)
		# init the manga view variables
		self.manga_display()
		log_d('Create manga display: OK')
		# init the chapter view variables
		#self.chapter_display()
		# init toolbar
		self.init_toolbar()
		log_d('Create toolbar: OK')
		# init status bar
		self.init_stat_bar()
		log_d('Create statusbar: OK')

		self.m_l_view_index = self.display.addWidget(self.manga_list_main)
		self.m_t_view_index = self.display.addWidget(self.manga_table_view)
		#self.display.addWidget(self.chapter_main)

		self.setCentralWidget(self.center)
		self.setWindowTitle("Happypanda")
		self.setWindowIcon(QIcon(gui_constants.APP_ICO_PATH))
		self.resize(gui_constants.MAIN_W, gui_constants.MAIN_H)
		self.show()
		log_d('Show window: OK')

		class upd_chk(QObject):
			UPDATE_CHECK = pyqtSignal(str)
			def __init__(self, **kwargs):
				super().__init__(**kwargs)
			def fetch_vs(self):
				import requests
				import time
				try:
					log_d('Checking Update')
					time.sleep(3)
					r = requests.get("https://raw.githubusercontent.com/Pewpews/happypanda/master/VS.txt")
					a = r.text
					vs = a.strip()
					self.UPDATE_CHECK.emit(vs)
				except:
					log_d('Checking Update: FAIL')
					pass

		update_instance = upd_chk()
		thread = QThread()
		update_instance.moveToThread(thread)
		update_instance.UPDATE_CHECK.connect(self.check_update)
		thread.started.connect(update_instance.fetch_vs)
		update_instance.UPDATE_CHECK.connect(lambda: update_instance.deleteLater)
		update_instance.UPDATE_CHECK.connect(lambda: thread.deleteLater)
		thread.start()
		log_d('Window Create: OK')
		#QTimer.singleShot(3000, self.check_update)

	def check_update(self, vs):
		try:
			if vs != gui_constants.vs:
				msgbox = QMessageBox()
				msgbox.setText("Update {} is available!".format(vs))
				msgbox.setDetailedText(
"""How to update:
1. Get the newest release from:
https://github.com/Pewpews/happypanda/releases

2. Overwrite your files with the new files.

Your database will not be touched without you being notified.""")
				msgbox.setStandardButtons(QMessageBox.Ok)
				msgbox.setDefaultButton(QMessageBox.Ok)
				msgbox.setWindowIcon(QIcon(gui_constants.APP_ICO_PATH))
				msgbox.exec()
		except:
			pass

	def init_stat_bar(self):
		self.status_bar = self.statusBar()
		self.status_bar.setMaximumHeight(20)
		self.status_bar.setSizeGripEnabled(False)
		self.stat_info = QLabel()
		self.stat_info.setIndent(5)
		self.sort_main = QAction("Asc", self)
		sort_menu = QMenu()
		self.sort_main.setMenu(sort_menu)
		s_by_title = QAction("Title", sort_menu)
		s_by_artist = QAction("Artist", sort_menu)
		sort_menu.addAction(s_by_title)
		sort_menu.addAction(s_by_artist)
		self.status_bar.addPermanentWidget(self.stat_info)
		#self.status_bar.addAction(self.sort_main)
		self.temp_msg = QLabel()
		self.temp_timer = QTimer()

		self.manga_list_view.series_model.ROWCOUNT_CHANGE.connect(self.stat_row_info)
		self.manga_list_view.series_model.STATUSBAR_MSG.connect(self.stat_temp_msg)
		self.manga_list_view.STATUS_BAR_MSG.connect(self.stat_temp_msg)
		self.manga_table_view.STATUS_BAR_MSG.connect(self.stat_temp_msg)
		self.stat_row_info()

	def stat_temp_msg(self, msg):
		self.temp_timer.stop()
		self.temp_msg.setText(msg)
		self.status_bar.addWidget(self.temp_msg)
		self.temp_timer.timeout.connect(self.temp_msg.clear)
		self.temp_timer.setSingleShot(True)
		self.temp_timer.start(5000)

	def stat_row_info(self):
		r = self.manga_list_view.model().rowCount()
		t = len(self.manga_list_view.model()._data)
		self.stat_info.setText("Loaded {} of {} ".format(r, t))

	def manga_display(self):
		"initiates the manga view"
		#list view
		self.manga_list_main = QWidget()
		self.manga_list_main.setContentsMargins(-10, -12, -10, -10)
		self.manga_list_layout = QHBoxLayout()
		self.manga_list_main.setLayout(self.manga_list_layout)

		self.manga_list_view = series.MangaView()
		self.manga_list_view.clicked.connect(self.popup)
		self.manga_list_view.manga_delegate.POPUP.connect(self.popup)
		self.popup_window = self.manga_list_view.manga_delegate.popup_window
		self.manga_list_layout.addWidget(self.manga_list_view)

		#table view
		self.manga_table_main = QWidget()
		self.manga_table_layout = QVBoxLayout()
		self.manga_table_main.setLayout(self.manga_table_layout)

		self.manga_table_view = series.MangaTableView()
		self.manga_table_view.series_model = self.manga_list_view.series_model
		self.manga_table_view.sort_model = self.manga_list_view.sort_model
		self.manga_table_view.setModel(self.manga_table_view.sort_model)
		self.manga_table_view.sort_model.change_model(self.manga_table_view.series_model)
		self.manga_table_view.setColumnWidth(gui_constants.FAV, 20)
		self.manga_table_view.setColumnWidth(gui_constants.ARTIST, 200)
		self.manga_table_view.setColumnWidth(gui_constants.TITLE, 400)
		self.manga_table_view.setColumnWidth(gui_constants.TAGS, 300)
		self.manga_table_view.setColumnWidth(gui_constants.TYPE, 100)
		self.manga_table_layout.addWidget(self.manga_table_view)


	def search(self, srch_string):
		case_ins = srch_string.lower()
		remove = '^$*+?{}[]\\|()'
		for x in remove:
			case_ins = case_ins.replace(x, '.')
		self.manga_list_view.sort_model.search(case_ins)

	def popup(self, index):
		if not self.popup_window.isVisible():
			m_x = QCursor.pos().x()
			m_y = QCursor.pos().y()
			d_w = QDesktopWidget().width()
			d_h = QDesktopWidget().height()
			p_w = gui_constants.POPUP_WIDTH
			p_h = gui_constants.POPUP_HEIGHT
			
			index_rect = self.manga_list_view.visualRect(index)
			index_point = self.manga_list_view.mapToGlobal(index_rect.topRight())
			# adjust so it doesn't go offscreen
			if d_w - m_x < p_w and d_h - m_y < p_h: # bottom
				self.popup_window.move(m_x-p_w+5, m_y-p_h)
			elif d_w - m_x > p_w and d_h - m_y < p_h:
				self.popup_window.move(m_x+5, m_y-p_h)
			elif d_w - m_x < p_w:
				self.popup_window.move(m_x-p_w+5, m_y+5)
			else:
				self.popup_window.move(index_point)

			self.popup_window.set_series(index.data(Qt.UserRole+1))
			self.popup_window.show()

	def favourite_display(self):
		"Switches to favourite display"
		if self.display.currentIndex() == self.m_l_view_index:
			self.manga_list_view.sort_model.fav_view()
		else:
			self.manga_table_view.sort_model.fav_view()

	def catalog_display(self):
		"Switches to catalog display"
		if self.display.currentIndex() == self.m_l_view_index:
			self.manga_list_view.sort_model.catalog_view()
		else:
			self.manga_table_view.sort_model.catalog_view()

	def settings(self):
		about = misc.About()

	def init_toolbar(self):
		self.toolbar = QToolBar()
		self.toolbar.setFixedHeight(30)
		self.toolbar.setWindowTitle("Show") # text for the contextmenu
		#self.toolbar.setStyleSheet("QToolBar {border:0px}") # make it user defined?
		self.toolbar.setMovable(False)
		self.toolbar.setFloatable(False)
		#self.toolbar.setIconSize(QSize(20,20))
		self.toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

		spacer_start = QWidget() # aligns the first actions properly
		spacer_start.setFixedSize(QSize(10, 1))
		self.toolbar.addWidget(spacer_start)

		favourite_view_icon = QIcon(gui_constants.STAR_BTN_PATH)
		favourite_view_action = QAction(favourite_view_icon, "Favourite", self)
		favourite_view_action.triggered.connect(self.favourite_display) #need lambda to pass extra args
		self.toolbar.addAction(favourite_view_action)

		catalog_view_icon = QIcon(gui_constants.HOME_BTN_PATH)
		catalog_view_action = QAction(catalog_view_icon, "Library", self)
		#catalog_view_action.setText("Catalog")
		catalog_view_action.triggered.connect(self.catalog_display) #need lambda to pass extra args
		self.toolbar.addAction(catalog_view_action)
		self.toolbar.addSeparator()

		series_icon = QIcon(gui_constants.PLUS_PATH)
		series_action = QAction(series_icon, "Add series...", self)
		series_action.triggered.connect(self.manga_list_view.SERIES_DIALOG.emit)
		series_menu = QMenu()
		series_menu.addSeparator()
		populate_action = QAction("Populate from folder...", self)
		populate_action.triggered.connect(self.populate)
		series_menu.addAction(populate_action)
		series_action.setMenu(series_menu)
		self.toolbar.addAction(series_action)

		spacer_middle = QWidget() # aligns buttons to the right
		spacer_middle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
		self.toolbar.addWidget(spacer_middle)
		
		self.grid_toggle_g_icon = QIcon(gui_constants.GRID_PATH)
		self.grid_toggle_l_icon = QIcon(gui_constants.LIST_PATH)
		self.grid_toggle = QAction(self.toolbar)
		self.grid_toggle.setIcon(self.grid_toggle_l_icon)
		self.grid_toggle.triggered.connect(self.toggle_view)
		self.toolbar.addAction(self.grid_toggle)

		completer = QCompleter(self)
		completer.setModel(self.manga_list_view.series_model)
		completer.setCaseSensitivity(Qt.CaseInsensitive)
		completer.setCompletionMode(QCompleter.PopupCompletion)
		completer.setCompletionRole(Qt.DisplayRole)
		completer.setCompletionColumn(gui_constants.TITLE)
		completer.setFilterMode(Qt.MatchContains)
		self.search_bar = QLineEdit()
		self.search_bar.setCompleter(completer)
		self.search_bar.textChanged[str].connect(self.search)
		self.search_bar.setPlaceholderText("Search title, artist (Tag: search tag)")
		self.search_bar.setMaximumWidth(200)
		self.toolbar.addWidget(self.search_bar)
		self.toolbar.addSeparator()
		settings_icon = QIcon(gui_constants.SETTINGS_PATH)
		settings_action = QAction(settings_icon, "Set&tings", self)
		settings_action.triggered.connect(self.settings)
		self.toolbar.addAction(settings_action)
		self.addToolBar(self.toolbar)
		
		spacer_end = QWidget() # aligns About action properly
		spacer_end.setFixedSize(QSize(10, 1))
		self.toolbar.addWidget(spacer_end)

	def toggle_view(self):
		"""
		Toggles the current display view
		"""
		if self.display.currentIndex() == self.m_l_view_index:
			self.display.setCurrentIndex(self.m_t_view_index)
			self.grid_toggle.setIcon(self.grid_toggle_g_icon)
		else:
			self.display.setCurrentIndex(self.m_l_view_index)
			self.grid_toggle.setIcon(self.grid_toggle_l_icon)

	# TODO: Improve this so that it adds to the series dialog,
	# so user can edit data before inserting (make it a choice)
	def populate(self):
		"Populates the database with series from local drive'"
		path = QFileDialog.getExistingDirectory(None, "Choose a folder containing your series'")
		if len(path) is not 0:
			data_thread = QThread()
			#loading_thread = QThread()
			loading = misc.Loading(self)
			if not loading.ON:
				misc.Loading.ON = True
				fetch_instance = fetch.Fetch()
				fetch_instance.series_path = path
				loading.show()

				def finished(status):
					def hide_loading():
						loading.hide()
					if status:
						if len(status) != 0:
							def add_series(series_list):
								class A(QObject):
									done = pyqtSignal()
									prog = pyqtSignal(int)
									def __init__(self, obj, parent=None):
										super().__init__(parent)
										self.obj = obj

									def add_to_db(self):
										p = 0
										for x in self.obj:
											seriesdb.SeriesDB.add_series(x)
											p += 1
											self.prog.emit(p)
										self.done.emit()

								loading.progress.setMaximum(len(series_list))
								a_instance = A(series_list)
								thread = QThread()
								def loading_show():
									loading.setText('Populating database.\nPlease wait...')
									loading.show()

								def loading_hide():
									loading.hide()
									self.manga_list_view.series_model.populate_data()

								a_instance.moveToThread(thread)
								a_instance.prog.connect(loading.progress.setValue)
								thread.started.connect(loading_show)
								thread.started.connect(a_instance.add_to_db)
								a_instance.done.connect(loading_hide)
								a_instance.done.connect(lambda: a_instance.deleteLater)
								a_instance.done.connect(lambda: thread.deleteLater)
								thread.start()

							data_thread.quit
							hide_loading()
							log_i('Populating DB from series folder: OK')
							series_list = misc.SeriesListView(self)
							series_list.SERIES.connect(add_series)
							for ser in status:
								item = misc.SeriesListItem(ser)
								item.setText(os.path.split(ser.path)[1])
								item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
								item.setCheckState(Qt.Checked)
								series_list.view_list.addItem(item)
							#self.manga_list_view.series_model.populate_data()
							series_list.show()
							# TODO: make it spawn a dialog instead (from utils.py or misc.py)
							misc.Loading.ON = False
						else:
							log_d('No new series was found')
							loading.setText("No new series found")
							data_thread.quit
							misc.Loading.ON = False

					else:
						log_e('Populating DB from series folder: FAIL')
						loading.setText("<font color=red>An error occured. Try restarting..</font>")
						loading.progress.setStyleSheet("background-color:red;")
						data_thread.quit

				def fetch_deleteLater():
					try:
						fetch_instance.deleteLater
					except NameError:
						pass

				def thread_deleteLater(): #NOTE: Isn't this bad?
					data_thread.deleteLater
					data_thread.quit()

				def a_progress(prog):
					loading.progress.setValue(prog)
					loading.setText("Searching for series...")

				fetch_instance.moveToThread(data_thread)
				fetch_instance.DATA_COUNT.connect(loading.progress.setMaximum)
				fetch_instance.PROGRESS.connect(a_progress)
				data_thread.started.connect(fetch_instance.local)
				fetch_instance.FINISHED.connect(finished)
				fetch_instance.FINISHED.connect(fetch_deleteLater)
				fetch_instance.FINISHED.connect(thread_deleteLater)
				data_thread.start()
				log_i('Populating DB from series folder')

	def closeEvent(self, event):
		try:
			for root, dirs, files in os.walk('temp', topdown=False):
				for name in files:
					os.remove(os.path.join(root, name))
				for name in dirs:
					os.rmdir(os.path.join(root, name))
			log_d('Empty temp on exit: OK')
		except:
			log_d('Empty temp on exit: FAIL')
		log_d('Normal Exit App: OK')
		super().closeEvent(event)
		app = QApplication.instance()
		app.quit()
		sys.exit()

if __name__ == '__main__':
	raise NotImplementedError("Unit testing not implemented yet!")