﻿#"""
#This file is part of Happypanda.
#Happypanda is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 2 of the License, or
#any later version.
#Happypanda is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with Happypanda.  If not, see <http://www.gnu.org/licenses/>.
#"""

import threading
import logging
import os
import math
import functools
import random
import datetime
import pickle
import enum
import time
import re as regex

from sqlalchemy.orm import joinedload

from PyQt5.QtCore import (Qt, QAbstractListModel, QModelIndex, QVariant,
                          QSize, QRect, QEvent, pyqtSignal, QThread,
                          QTimer, QPointF, QSortFilterProxyModel,
                          QAbstractTableModel, QItemSelectionModel,
                          QPoint, QRectF, QDate, QDateTime, QObject,
                          QEvent, QSizeF, QMimeData, QByteArray, QTime,
                          QEasingCurve, QPersistentModelIndex)
from PyQt5.QtGui import (QPixmap, QBrush, QColor, QPainter, 
                         QPen, QTextDocument,
                         QMouseEvent, QHelpEvent,
                         QPixmapCache, QCursor, QPalette, QKeyEvent,
                         QFont, QTextOption, QFontMetrics, QFontMetricsF,
                         QTextLayout, QPainterPath, QScrollPrepareEvent,
                         QWheelEvent, QPolygonF, QLinearGradient, QStandardItemModel,
                         QStandardItem, QImage)
from PyQt5.QtWidgets import (QListView, QFrame, QLabel,
                             QStyledItemDelegate, QStyle,
                             QMenu, QAction, QToolTip, QVBoxLayout,
                             QSizePolicy, QTableWidget, QScrollArea,
                             QHBoxLayout, QFormLayout, QDesktopWidget,
                             QWidget, QHeaderView, QTableView, QApplication,
                             QMessageBox, QActionGroup, QScroller, QStackedLayout,
                             QTreeView, QPushButton)

import gallerydb
import app_constants
import db_constants
import misc
import gallerydialog
import io_misc
import utils
import db

log = logging.getLogger(__name__)
log_i = log.info
log_d = log.debug
log_w = log.warning
log_e = log.error
log_c = log.critical

class HierarchicalFilteringProxyModel(QSortFilterProxyModel):
    """
    SHAMELESSLY STOLEN FROM: https://github.com/mds-dev/shotgun_dev
    Inherited from a :class: QSortFilterProxyModel`, this class implements filtering across all 
    levels of a hierarchy in a hierarchical (tree-based) model and provides a simple
    interface for derived classes so that all they need to do is filter a single item
    as requested.
    """
    
    
    class _IndexAcceptedCache(object):
        """
        Cached 'accepted' values for indexes.  Uses a dictionary that maps a key to a tuple 
        containing a QPersistentModelIndex for the index and its accepted value.
            key -> (QPersistentModelIndex, accepted)
        In recent versions of PySide, the key is just a QPersistentModelIndex which has the
        advantage that cache entries don't become invalid when rows are added/moved.
        In older versions of PySide (e.g. in 1.0.9 used by Nuke 6/7/8/9) this isn't possible 
        as QPersistentModelIndex isn't hashable so instead a tuple of the row hierarchy is used 
        and then when looking up the cached value, the persistent model index is used to ensure 
        that the cache entry is still valid.
        """
        def __init__(self):
            """
            Construction
            """
            self._cache = {}
            self.enabled = True
            self._cache_hits = 0
            self._cache_misses = 0

            # ideally we'd use QPersistentModelIndexes to key into the cache but these 
            # aren't hashable in earlier versions of PySide!
            self._use_persistent_index_keys = True
            try:
                # wouldn't it be nice if there were an in-built mechanism to test if a type was
                # hashable!
                hash(QPersistentModelIndex())
            except:
                self._use_persistent_index_keys = False

        @property
        def cache_hit_miss_ratio(self):
            """
            Useful for debug to see how many cache hits vs misses there are
            """
            total_cache_queries = self._cache_hits + self._cache_misses
            if total_cache_queries > 0:
                return float(self._cache_hits) / float(total_cache_queries)
            else:
                return 0

        @property
        def size(self):
            """
            Return the current size of the cache
            """
            return len(self._cache)

        def add(self, index, accepted):
            """
            Add the specified index to the cache together with it's accepted state
            :param index:       The QModelIndex to be added
            :param accepted:    True if the model index is accepted by the filtering, False if not.
            """
            if not self.enabled:
                return

            cache_key = self._gen_cache_key(index)
            p_index = cache_key if self._use_persistent_index_keys else QPersistentModelIndex(index)
            self._cache[cache_key] = (p_index, accepted)

        def remove(self, index):
            """
            Remove the specified index from the cache.
            :param index:   The QModelIndex to remove from the cache
            """
            if not self.enabled:
                return

            cache_key = self._gen_cache_key(index)
            if cache_key in self._cache:
                del self._cache[cache_key]

        def get(self, index):
            """
            Get the accepted state for the specified index in the cache.
            :param index:   The QModelIndex to get the accepted state for
            :returns:       The accepted state if the index was found in the cache, otherwise None
            """
            if not self.enabled:
                return None

            cache_key = self._gen_cache_key(index)
            cache_value = self._cache.get(cache_key)
            if not cache_value:
                self._cache_misses += 1
                return None

            p_index, accepted = cache_value
            if p_index and p_index == index:
                # index and cached value are still valid!
                self._cache_hits += 1
                return accepted
            else:
                # row has changed so results are bad!
                self._cache_misses += 1
                return None

        def minimize(self):
            """
            Minimize the size of the cache by removing any entries that are no longer valid
            """
            if not self.enabled:
                return

            self._cache = dict([(k, v) for k, v in self._cache.iteritems() if v[0].isValid()])

        def clear(self):
            """
            Clear the cache
            """
            if not self.enabled:
                return

            self._cache = {}

        def _gen_cache_key(self, index):
            """
            Generate the key for the specified index in the cache.
            :param index:   The QModelIndex to generate a cache key for
            :returns:       The key of the index in the cache
            """
            # ideally we would just use persistent model indexes but these aren't hashable
            # in early versions of PySide :(
            if self._use_persistent_index_keys:
                return QPersistentModelIndex(index)

            # the cache key is a tuple of all the row indexes of the parent
            # hierarchy for the index.  First, find the row indexes:
            rows = []
            parent_idx = index
            while parent_idx.isValid():
                rows.append(parent_idx.row())
                parent_idx = parent_idx.parent()

            # return a tuple of the reversed indexes:
            return tuple(reversed(rows))

    def __init__(self, parent=None):
        """
        :param parent:    The parent QObject to use for this instance
        :type parent:     :class:`~PySide.QtGui.QWidget`  
        """
        super().__init__(parent)

        self._accepted_cache = HierarchicalFilteringProxyModel._IndexAcceptedCache()
        self._child_accepted_cache = HierarchicalFilteringProxyModel._IndexAcceptedCache()

    def enable_caching(self, enable=True):
        """
        Allow control over enabling/disabling of the accepted cache used to accelerate
        filtering.  Can be used for debug purposes to ensure the caching isn't the cause
        of incorrect filtering/sorting or instability!
        :param enable:    True if caching should be enabled, False if it should be disabled. 
        """
        # clear the accepted cache - this will make sure we don't use out-of-date 
        # information from the cache
        self._dirty_all_accepted()
        self._accepted_cache.enabled = enable
        self._child_accepted_cache.enabled = enable

    def _is_row_accepted(self, src_row, src_parent_idx, parent_accepted):
        """
        Override this method to decide if the specified row should be accepted or not by
        the filter.
        This should be overridden instead of filterAcceptsRow in derived classes
        :param src_row:         The row in the source model to filter
        :param src_parent_idx:  The parent QModelIndex instance to filter
        :param parent_accepted: True if a parent item has been accepted by the filter
        :returns:               True if this index should be accepted, otherwise False
        """
        raise NotImplementedError("HierarchicalFilteringProxyModel._is_row_accepted() must be overridden"
                                  " in derived classes!")

    # -------------------------------------------------------------------------------
    # Overriden base class methods

    def setFilterRegExp(self, reg_exp):
        """
        Overriden base class method to set the filter regular expression
        """
        self._dirty_all_accepted()
        super().setFilterRegExp(reg_exp)

    def setFilterFixedString(self, pattern):
        """
        Overriden base class method to set the filter fixed string
        """
        self._dirty_all_accepted()
        super().setFilterFixedString(pattern)

    def setFilterCaseSensitivity(self, cs):
        """
        Overriden base class method to set the filter case sensitivity
        """
        self._dirty_all_accepted()
        super().setFilterCaseSensitivity(cs)

    def setFilterKeyColumn(self, column):
        """
        Overriden base class method to set the filter key column
        """
        self._dirty_all_accepted()
        super().setFilterKeyColumn(column)

    def setFilterRole(self, role):
        """
        Overriden base class method to set the filter role
        """
        self._dirty_all_accepted()
        super().setFilterRole(role)

    def invalidate(self):
        """
        Overriden base class method used to invalidate sorting and filtering.
        """
        self._dirty_all_accepted()
        # call through to the base class:
        super().invalidate()

    def invalidateFilter(self):
        """
        Overriden base class method used to invalidate the current filter.
        """
        self._dirty_all_accepted()
        # call through to the base class:
        super().invalidateFilter()

    def filterAcceptsRow(self, src_row, src_parent_idx):
        """
        Overriden base class method used to determine if a row is accepted by the
        current filter.
        This implementation checks both up and down the hierarchy to determine if
        this row should be accepted.
        :param src_row:         The row in the source model to filter
        :param src_parent_idx:  The parent index in the source model to filter
        :returns:               True if the row should be accepted by the filter, False
                                otherwise
        """
        # get the source index for the row:
        src_model = self.sourceModel()
        src_idx = src_model.index(src_row, 0, src_parent_idx)

        # first, see if any children of this item are known to already be accepted
        child_accepted = self._child_accepted_cache.get(src_idx)
        if child_accepted == True:
            # child is accepted so this item must also be accepted
            return True

        # next, we need to determine if the parent item has been accepted.  To do this,
        # search up the hierarchy stopping at the first parent that we know for sure if
        # it has been accepted or not.
        upstream_indexes = []
        current_idx = src_idx
        parent_accepted = False
        while current_idx and current_idx.isValid():
            accepted = self._accepted_cache.get(current_idx)
            if accepted != None:
                parent_accepted = accepted
                break
            upstream_indexes.append(current_idx)
            current_idx = current_idx.parent()

        # now update the accepted status for items that we don't know
        # for sure, working from top to bottom in the hierarchy ending
        # on the index we are checking for:
        for idx in reversed(upstream_indexes):
            accepted = self._is_row_accepted(idx.row(), idx.parent(), parent_accepted)
            self._accepted_cache.add(idx, accepted)
            parent_accepted = accepted

        if parent_accepted:
            # the index we are testing was accepted!
            return True
        elif src_model.hasChildren(src_idx):
            # even though the parent wasn't accepted, it may still be needed if one or more
            # children/grandchildren/etc. are accepted:
            return self._is_child_accepted_r(src_idx, parent_accepted)
        else:
            # index wasn't accepted and has no children
            return False  

    def setSourceModel(self, model):
        """
        Overridden base method that we use to keep track of when rows are inserted into the 
        source model
        :param model:   The source model to track
        """
        # if needed, disconnect from the previous source model:
        prev_source_model = self.sourceModel()
        if prev_source_model:
            prev_source_model.rowsInserted.disconnect(self._on_source_model_rows_inserted)
            prev_source_model.dataChanged.disconnect(self._on_source_model_data_changed)
            prev_source_model.modelAboutToBeReset.disconnect(self._on_source_model_about_to_be_reset)

        # clear out the various caches:
        self._dirty_all_accepted()

        # call base implementation:
        super().setSourceModel(model)

        # connect to the new model:
        if model:
            model.rowsInserted.connect(self._on_source_model_rows_inserted)
            model.dataChanged.connect(self._on_source_model_data_changed)
            model.modelAboutToBeReset.connect(self._on_source_model_about_to_be_reset)

    # -------------------------------------------------------------------------------
    # Private methods

    def _is_child_accepted_r(self, idx, parent_accepted):
        """
        Recursively check children to see if any of them have been accepted.
        :param idx:             The model index whose children should be checked
        :param parent_accepted: True if a parent item has been accepted
        :returns:               True if a child of the item is accepted by the filter
        """
        model = idx.model()

        # check to see if any children of this item are known to have been accepted:
        child_accepted = self._child_accepted_cache.get(idx)
        if child_accepted != None:
            # we already computed this so just return the result
            return child_accepted

        # need to recursively iterate over children looking for one that is accepted:
        child_accepted = False
        for ci in range(model.rowCount(idx)):
            child_idx = idx.child(ci, 0)

            # check if child item is in cache:
            accepted = self._accepted_cache.get(child_idx)
            if accepted == None:
                # it's not so lets see if it's accepted and add to the cache:
                accepted = self._is_row_accepted(child_idx.row(), idx, parent_accepted)
                self._accepted_cache.add(child_idx, accepted)

            if model.hasChildren(child_idx):
                child_accepted = self._is_child_accepted_r(child_idx, accepted)
            else:
                child_accepted = accepted

            if child_accepted:
                # found a child that was accepted so we can stop searching
                break

        # cache if any children were accepted:
        self._child_accepted_cache.add(idx, child_accepted)
        return child_accepted

    def _dirty_all_accepted(self):
        """
        Dirty/clear the accepted caches
        """
        self._accepted_cache.clear()
        self._child_accepted_cache.clear()

    def _dirty_accepted_rows(self, parent_idx, start, end):
        """
        Dirty the specified rows from the accepted caches.  This will remove any entries in
        either the accepted or the child accepted cache that match the start/end rows for the
        specified parent index.
        This also dirties the parent hierarchy to ensure that any filtering is re-calculated for
        those parent items.
        :param parent_idx:  The parent model index to dirty rows for
        :param start:       The first row in to dirty
        :param end:         The last row to dirty
        """
        # clear all rows from the accepted caches
        for row in range(start, end+1):
            idx = self.sourceModel().index(row, 0, parent_idx)
            self._child_accepted_cache.remove(idx)
            self._accepted_cache.remove(idx)

        # remove parent hierarchy from caches as well:
        while parent_idx.isValid():
            self._child_accepted_cache.remove(parent_idx)
            self._accepted_cache.remove(parent_idx)
            parent_idx = parent_idx.parent()

    def _on_source_model_data_changed(self, start_idx, end_idx):
        """
        Slot triggered when data for one or more items in the source model changes.
        Data in the source model changing may mean that the filtering for an item changes.  If this
        is the case then we need to make sure we clear any affected entries from the cache
        :param start_idx:   The index of the first row in the range of model items that have changed
        :param start_idx:   The index of the last row in the range of model items that have changed
        """
        if (not start_idx.isValid() or not end_idx.isValid()
            or start_idx.model() != self.sourceModel() 
            or end_idx.model() != self.sourceModel()):
            # invalid input parameters so ignore!
            return

        parent_idx = start_idx.parent()
        if parent_idx != end_idx.parent():
            # this should never happen but just in case, dirty the entire cache:
            self._dirty_all_accepted()

        # dirty specific rows in the caches:
        self._dirty_accepted_rows(parent_idx, start_idx.row(), end_idx.row())

    def _on_source_model_rows_inserted(self, parent_idx, start, end):
        """
        Slot triggered when rows are inserted into the source model.
        There appears to be a limitation with the QSortFilterProxyModel that breaks sorting
        of newly added child rows when the parent row has previously been filtered out.  This
        can happen when the model data is lazy-loaded as the filtering may decide that as
        there are no valid children, then the parent should be filtered out.  However, when
        matching children later get added, the parent then matches but the children don't get
        sorted correctly!
        The workaround is to detect when children are added to a parent that was previously
        filtered out and force the whole proxy model to be invalidated (so that the filtering
        and sorting are both applied from scratch).
        The alternative would be to implement our own version of the QSortFilterProxyModel!
        :param parent_idx:  The index of the parent model item
        :param start:       The first row that was inserted into the source model
        :param end:         The last row that was inserted into the source model
        """
        if (not parent_idx.isValid()
            or parent_idx.model() != self.sourceModel()):
            # invalid input parameters so ignore!
            return

        # dirty specific rows in the caches:
        self._dirty_accepted_rows(parent_idx, start, end)

    def _on_source_model_about_to_be_reset(self):
        """
        Called when the source model is about to be reset.
        """
        # QPersistentModelIndex are constantly being tracked by the owning model so that their references
        # are always valid even after nodes siblings removed. When a model is about to be reset
        # we are guaranteed that the indices won't be valid anymore, so clearning thoses indices now
        # means the source model won't have to keep updating them as the tree is being cleared, thus slowing
        # down the reset.
        self._dirty_all_accepted()

class ModelDataLoader(QObject):
    ""

    item_loaded = pyqtSignal(QModelIndex, db.Base)
    finished = pyqtSignal()

    def __init__(self, modeldatatype):
        super().__init__()
        self.other_thread = QThread(self)
        self.moveToThread(self.other_thread)
        self.other_thread.start()
        self._idtrack = {'coll':None}

    def fetch_more(self, idx):
        ""
        assert isinstance(idx, QModelIndex)
        self.session = db_constants.SESSION()
        dbitem = idx.data(app_constants.ITEM_ROLE)
        if not dbitem:
            dbmodel = db.Collection
            q = self.session.query(dbmodel)
            dbitem = 'coll'
        elif isinstance(dbitem, db.Collection):
            dbmodel = db.Gallery
            q = self.session.query(dbmodel).filter(dbmodel.collection == dbitem)
        elif isinstance(dbitem, db.Gallery):
            dbmodel = db.Page
            q = self.session.query(dbmodel).filter(dbmodel.gallery == dbitem)
        else:
            raise NotImplementedError

        if not dbitem in self._idtrack:
            self._idtrack[dbitem] = None
        last_id = self._idtrack[dbitem]

        if last_id:
            q = self.session.query(dbmodel).filter(dbmodel.id > last_id)

        for it in q.order_by(dbmodel.id):
            self._idtrack[dbitem] = it.id
            self.session.expunge_all()
            self.item_loaded.emit(idx, it)
        self.finished.emit()

class BaseItem(QStandardItem):

    def __init__(self):
        super().__init__()
        self._delegate = {}

    def data(self, role = Qt.UserRole+1):

        if role == app_constants.DELEGATE_ROLE:
            return self._delegate
        elif role == app_constants.QITEM_ROLE:
            return self

        return super().data(role)

    def setData(self, value, role = Qt.UserRole+1):

        if role == app_constants.DELEGATE_ROLE:
            self._delegate[value[0]] = value[1]

        return super().setData(value, role)

class CollectionItem(BaseItem):

    def __init__(self, collection):
        assert isinstance(collection, db.Collection)
        super().__init__()
        self._item = collection

    def data(self, role = Qt.UserRole+1):
        sess = db.object_session(self._item)
        if not sess:
            sess = db_constants.SESSION()
            sess.merge(self._item)

        if role in (Qt.DisplayRole, app_constants.TITLE_ROLE):
            return self._item.title
        elif role == Qt.DecorationRole:
            return QImage(self._item.profile)
        elif role == app_constants.ITEM_ROLE:
            return self._item
        elif role == app_constants.INFO_ROLE:
            return self._item.info
        elif role == app_constants.RATING_ROLE:
            return self._item.rating

        return super().data(role)

    def setData(self, value, role = Qt.UserRole+1):

        if role == Qt.DisplayRole:
            self._item.title = value
        elif role == app_constants.TITLE_ROLE:
            self._item.title = value
        elif role == app_constants.INFO_ROLE:
            self._item.info = value

        return super().setData(value, role)

    @classmethod
    def type(self):
        return app_constants.COLLECTION_TYPE

class GalleryItem(BaseItem):

    def __init__(self, gallery):
        assert isinstance(gallery, db.Gallery)
        super().__init__()
        self._item = gallery

    def data(self, role = Qt.UserRole+1):
        sess = db.object_session(self._item)
        if not sess:
            sess = db_constants.SESSION()
            sess.merge(self._item)

        if role in (Qt.DisplayRole, app_constants.TITLE_ROLE):
            return self._item.title
        elif role == Qt.DecorationRole:
            return QImage(self._item.profile)
        elif role == app_constants.ITEM_ROLE:
            return self._item
        elif role == app_constants.ARTIST_ROLE:
            if not self._item.artists:
                return []
            return self._item.artists
        elif role == app_constants.FAV_ROLE:
            return self._item.fav
        elif role == app_constants.INFO_ROLE:
            return self._item.info
        elif role == app_constants.TYPE_ROLE:
            return self._item.type
        elif role == app_constants.LANGUAGE_ROLE:
            return self._item.language
        elif role == app_constants.RATING_ROLE:
            return self._item.rating
        elif role == app_constants.TIMES_READ_ROLE:
            return self._item.times_read
        elif role == app_constants.STATUS_ROLE:
            return self._item.status
        elif role == app_constants.PUB_DATE_ROLE:
            return self._item.pub_date
        elif role == app_constants.DATE_ADDED_ROLE:
            return self._item.timestamp
        elif role == app_constants.NUMBER_ROLE:
            return self._item.number
        elif role == app_constants.PARENT_ROLE:
            return self._item.parent
        elif role == app_constants.COLLECTION_ROLE:
            return self._item.collection
        elif role == app_constants.TAGS_ROLE:
            return self._item.tags.all()
        elif role == app_constants.CIRCLES_ROLE:
            return self._item.circles.all()
        elif role == app_constants.URLS_ROLE:
            return self._item.urls.all()

        return super().data(role)

    def setData(self, value, role = Qt.UserRole+1):

        if role == Qt.DisplayRole:
            self._item.title = value
        elif role == app_constants.TITLE_ROLE:
            self._item.title = value
        elif role == app_constants.INFO_ROLE:
            self._item.info = value

        return super().setData(value, role)

    @classmethod
    def type(self):
        return app_constants.GALLERY_TYPE

class PageItem(BaseItem):

    def __init__(self, page):
        assert isinstance(page, db.Page)
        super().__init__()
        self._item = page

    def data(self, role = Qt.UserRole+1):
        sess = db.object_session(self._item)
        if not sess:
            sess = db_constants.SESSION()
            sess.merge(self._item)

        if role in (Qt.DisplayRole, app_constants.TITLE_ROLE):
            pname = "Page"
            if self._item.number:
                pname += " " + str(self._item.number)
            return pname
        elif role == Qt.DecorationRole:
            return QImage(self._item.profile)
        elif role == app_constants.ITEM_ROLE:
            return self._item
        elif role == app_constants.NUMBER_ROLE:
            return self._item.number
        elif role == app_constants.PARENT_ROLE:
            return self._item.gallery
        elif role == app_constants.HASH_ROLE:
            _hash = None
            if self._item.hash:
                _hash = self._item.hash.name
            return _hash

        return super().data(role)

    def setData(self, value, role = Qt.UserRole+1):

        if role == Qt.DisplayRole:
            self._item.title = value
        elif role == app_constants.TITLE_ROLE:
            self._item.title = value

        return super().setData(value, role)

    @classmethod
    def type(self):
        return app_constants.PAGE_TYPE


class DBSearch(QObject):
    FINISHED = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.allowed_collections = set()
        self.allowed_galleries = set()
        self._session = None

        # filtering
        self.fav = False
        self._item_list = None


    def set_gallery_list(self, g_list):
        self._item_list = g_list

    def set_fav(self, new_fav):
        self.fav = new_fav

    def search(self, term, args):
        term = ' '.join(term.split())
        search_pieces = utils.get_terms(term)

        self._filter(search_pieces, args)
        self.FINISHED.emit()

    def _update_ids(self, current_set, last_set, excluded_set, is_exclude):
        if last_set and is_exclude:
            updated_set = last_set
        elif last_set:
            updated_set = last_set & current_set
        else:
            updated_set = current_set

        if is_exclude:
            updated_set -= excluded_set

        return updated_set

    def _filter(self, terms, args):
        if self._session:
            self._session = db_constants.SESSION()
        self.allowed_collections.clear()
        self.allowed_galleries.clear()
        if not terms:
            terms = ['']

        last_coll = set()
        [last_coll.add(x[0]) for x in db.Collection.search('', session=self._session) if x]
        last_gall = set()
        [last_gall.add(x[0]) for x in db.Gallery.search('', session=self._session) if x]
        excluded_coll = set()
        excluded_gall = set()
        for term in terms:
            coll_set = set()
            if not self.fav:
                [coll_set.add(x[0]) for x in db.Collection.search(term, session=self._session) if x]
            gall_set = set()
            [gall_set.add(x[0]) for x in db.Gallery.search(term, fav=self.fav, session=self._session) if x]
            
            is_exclude = True if term and term[0] == '-' else False
            if is_exclude:
                excluded_coll |= coll_set
            self.allowed_collections = self._update_ids(coll_set, last_coll, excluded_coll, is_exclude)
            if not is_exclude:
                last_coll = coll_set

            if is_exclude:
                excluded_gall |= gall_set
            self.allowed_galleries = self._update_ids(gall_set, last_gall, excluded_gall, is_exclude)
            if not is_exclude:
                last_gall = gall_set

        if app_constants.DEBUG:
            print(self.allowed_collections)
            print(self.allowed_galleries)

class SortFilterModel(HierarchicalFilteringProxyModel):
    _DO_SEARCH = pyqtSignal(str, object)
    _CHANGE_FAV = pyqtSignal(bool)
    _SET_GALLERY_LIST = pyqtSignal(object)

    HISTORY_SEARCH_TERM = pyqtSignal(str)
    # Navigate terms
    NEXT, PREV = range(2)
    # Views
    CAT_VIEW, FAV_VIEW = range(2)

    def __init__(self, parent):
        super().__init__(parent)
        self.parent_widget = parent
        self._data = app_constants.GALLERY_DATA
        self._search_ready = False
        self.current_term = ''
        self.terms_history = []
        self.current_term_history = 0
        self.current_gallery_list = None
        self.current_args = []
        self.current_view = self.CAT_VIEW
        self.setDynamicSortFilter(True)
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setSortLocaleAware(True)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.enable_drag = False

        self._db_search = DBSearch()
        self._db_search.FINISHED.connect(self.invalidateFilter)
        self._db_search.moveToThread(app_constants.GENERAL_THREAD)
        self._DO_SEARCH.connect(self._db_search.search)
        self._SET_GALLERY_LIST.connect(self._db_search.set_gallery_list)
        self._CHANGE_FAV.connect(self._db_search.set_fav)

    def navigate_history(self, direction=PREV):
        new_term = ''
        if self.terms_history:
            if direction == self.NEXT:
                if self.current_term_history < len(self.terms_history) - 1:
                    self.current_term_history += 1
            elif direction == self.PREV:
                if self.current_term_history > 0:
                    self.current_term_history -= 1
            new_term = self.terms_history[self.current_term_history]
            if new_term != self.current_term:
                self.init_search(new_term, history=False)
        return new_term

    def set_gallery_list(self, g_list=None):
        self.current_gallery_list = g_list
        self._SET_GALLERY_LIST.emit(g_list)
        self.refresh()

    def fav_view(self):
        self._CHANGE_FAV.emit(True)
        self.refresh()
        self.current_view = self.FAV_VIEW

    def catalog_view(self):
        self._CHANGE_FAV.emit(False)
        self.refresh()
        self.current_view = self.CAT_VIEW

    def refresh(self):
        self._DO_SEARCH.emit(self.current_term, self.current_args)

    def init_search(self, term, args=None, **kwargs):
        """
        Receives a search term and initiates a search
        args should be a list of Search enums
        """
        if not args:
            args = self.current_args
        history = kwargs.pop('history', True)
        if history:
            if len(self.terms_history) > 10:
                self.terms_history = self.terms_history[-10:]
            self.terms_history.append(term)

            self.current_term_history = len(self.terms_history) - 1
            if self.current_term_history < 0:
                self.current_term_history = 0

        self.current_term = term
        if not history:
            self.HISTORY_SEARCH_TERM.emit(term)
        self.current_args = args
        self._db_search.search(term, args)
        #self._DO_SEARCH.emit(term, args)

    def _is_row_accepted(self, src_row, src_parent_idx, parent_accepted):
        index = self.sourceModel().index(src_row, 0, src_parent_idx)
        if index.isValid():
            itemtype = index.data(app_constants.QITEM_ROLE).type()
            if itemtype == PageItem.type() and parent_accepted:
                return True
            itemid = index.data(app_constants.ITEM_ROLE).id
            if itemtype == CollectionItem.type():
                if itemid in self._db_search.allowed_collections:
                    return True
            elif itemtype == GalleryItem.type():
                if itemid in self._db_search.allowed_galleries:
                    return True
            else:
                return True
        return False

    def change_model(self, model):
        self.setSourceModel(model)
        if hasattr(model, '_loader'):
            model._loader.finished.connect(self.refresh)
        self.refresh()

    def status_b_msg(self, msg):
        self.sourceModel().status_b_msg(msg)

    def canDropMimeData(self, data, action, row, coloumn, index):
        return False
        if not data.hasFormat("list/gallery"):
            return False
        return True

    def dropMimeData(self, data, action, row, coloumn, index):
        if not self.canDropMimeData(data, action, row, coloumn, index):
            return False
        if action == Qt.IgnoreAction:
            return True
        
        # if the drop occured on an item
        if not index.isValid():
            return False

        g_list = pickle.loads(data.data("list/gallery").data())
        item_g = index.data(GalleryModel.GALLERY_ROLE)
        # ignore false positive
        for g in g_list:
            if g.id == item_g.id:
                return False

        txt = 'galleries' if len(g_list) > 1 else 'gallery'
        msg = QMessageBox(self.parent_widget)
        msg.setText("Are you sure you want to merge the galleries into this gallery as chapter(s)?".format(txt))
        msg.setStandardButtons(msg.Yes | msg.No)
        if msg.exec() == msg.No:
            return False
        
        # TODO: finish this

        return True

    def mimeTypes(self):
        return ['list/gallery'] + super().mimeTypes()

    def mimeData(self, index_list):
        data = QMimeData()
        g_list = []
        for idx in index_list:
            g = idx.data(GalleryModel.GALLERY_ROLE)
            if g != None:
                g_list.append(g)
        data.setData("list/gallery", QByteArray(pickle.dumps(g_list)))
        return data

    def flags(self, index):
        default_flags = super().flags(index)
        
        if self.enable_drag:
            if (index.isValid()):
                return Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled | default_flags
            else:
                return Qt.ItemIsDropEnabled | default_flags
        return default_flags

    def supportedDragActions(self):
        return Qt.ActionMask

class StarRating():
    # enum EditMode
    Editable, ReadOnly = range(2)

    PaintingScaleFactor = 18

    def __init__(self, starCount=1, maxStarCount=5):
        self._starCount = starCount
        self._maxStarCount = maxStarCount

        self.starPolygon = QPolygonF([QPointF(1.0, 0.5)])
        for i in range(5):
            self.starPolygon << QPointF(0.5 + 0.5 * math.cos(0.8 * i * math.pi),
                                        0.5 + 0.5 * math.sin(0.8 * i * math.pi))

        self.diamondPolygon = QPolygonF()
        self.diamondPolygon << QPointF(0.4, 0.5) \
                            << QPointF(0.5, 0.4) \
                            << QPointF(0.6, 0.5) \
                            << QPointF(0.5, 0.6) \
                            << QPointF(0.4, 0.5)

    def starCount(self):
        return self._starCount

    def maxStarCount(self):
        return self._maxStarCount

    def setStarCount(self, starCount):
        self._starCount = starCount

    def setMaxStarCount(self, maxStarCount):
        self._maxStarCount = maxStarCount

    def sizeHint(self):
        return self.PaintingScaleFactor * QSize(self._maxStarCount, 1)

    def paint(self, painter, rect, editMode=ReadOnly):
        painter.save()

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        painter.setBrush(QBrush(QColor(0, 0, 0, 100)))
        painter.drawRoundedRect(QRectF(rect), 2, 2)

        painter.setBrush(QBrush(Qt.yellow))

        scaleFactor = self.PaintingScaleFactor
        yOffset = (rect.height() - scaleFactor) / 2
        painter.translate(rect.x(), rect.y() + yOffset)
        painter.scale(scaleFactor, scaleFactor)

        for i in range(self._maxStarCount):
            if i < self._starCount:
                painter.drawPolygon(self.starPolygon, Qt.WindingFill)
            elif editMode == StarRating.Editable:
                painter.drawPolygon(self.diamondPolygon, Qt.WindingFill)

            painter.translate(1.0, 0.0)

        painter.restore()

class GalleryModel(QAbstractTableModel):
    """
    Model for Model/View/Delegate framework
    """
    GALLERY_ROLE = Qt.UserRole + 1
    ARTIST_ROLE = Qt.UserRole + 2
    FAV_ROLE = Qt.UserRole + 3
    DATE_ADDED_ROLE = Qt.UserRole + 4
    PUB_DATE_ROLE = Qt.UserRole + 5
    TIMES_READ_ROLE = Qt.UserRole + 6
    LAST_READ_ROLE = Qt.UserRole + 7
    TIME_ROLE = Qt.UserRole + 8
    RATING_ROLE = Qt.UserRole + 9

    ROWCOUNT_CHANGE = pyqtSignal()
    STATUSBAR_MSG = pyqtSignal(str)
    CUSTOM_STATUS_MSG = pyqtSignal(str)
    ADDED_ROWS = pyqtSignal()
    ADD_MORE = pyqtSignal()

    REMOVING_ROWS = False

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.dataChanged.connect(lambda: self.status_b_msg("Edited"))
        self.dataChanged.connect(lambda: self.ROWCOUNT_CHANGE.emit())
        self.layoutChanged.connect(lambda: self.ROWCOUNT_CHANGE.emit())
        self.CUSTOM_STATUS_MSG.connect(self.status_b_msg)
        self._TITLE = app_constants.TITLE
        self._ARTIST = app_constants.ARTIST
        self._TAGS = app_constants.TAGS
        self._TYPE = app_constants.TYPE
        self._FAV = app_constants.FAV
        self._CHAPTERS = app_constants.CHAPTERS
        self._LANGUAGE = app_constants.LANGUAGE
        self._LINK = app_constants.LINK
        self._DESCR = app_constants.DESCR
        self._DATE_ADDED = app_constants.DATE_ADDED
        self._PUB_DATE = app_constants.PUB_DATE

        self._data = data
        self._data_count = 0 # number of items added to model
        self._gallery_to_add = []
        self._gallery_to_remove = []

    def status_b_msg(self, msg):
        self.STATUSBAR_MSG.emit(msg)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return QVariant()
        if index.row() >= len(self._data) or \
            index.row() < 0:
            return QVariant()

        current_row = index.row() 
        current_gallery = self._data[current_row]
        current_column = index.column()

        def column_checker():
            if current_column == self._TITLE:
                title = current_gallery.title
                return title
            elif current_column == self._ARTIST:
                artist = current_gallery.artist
                return artist
            elif current_column == self._TAGS:
                tags = utils.tag_to_string(current_gallery.tags)
                return tags
            elif current_column == self._TYPE:
                type = current_gallery.type
                return type
            elif current_column == self._FAV:
                if current_gallery.fav == 1:
                    return u'\u2605'
                else:
                    return ''
            elif current_column == self._CHAPTERS:
                return len(current_gallery.chapters)
            elif current_column == self._LANGUAGE:
                return current_gallery.language
            elif current_column == self._LINK:
                return current_gallery.link
            elif current_column == self._DESCR:
                return current_gallery.info
            elif current_column == self._DATE_ADDED:
                g_dt = "{}".format(current_gallery.date_added)
                qdate_g_dt = QDateTime.fromString(g_dt, "yyyy-MM-dd HH:mm:ss")
                return qdate_g_dt
            elif current_column == self._PUB_DATE:
                g_pdt = "{}".format(current_gallery.pub_date)
                qdate_g_pdt = QDateTime.fromString(g_pdt, "yyyy-MM-dd HH:mm:ss")
                if qdate_g_pdt.isValid():
                    return qdate_g_pdt
                else:
                    return 'No date set'

        # TODO: name all these roles and put them in app_constants...

        if role == Qt.DisplayRole:
            return column_checker()
        # for artist searching
        if role == self.ARTIST_ROLE:
            artist = current_gallery.artist
            return artist

        if role == Qt.DecorationRole:
            pixmap = current_gallery.profile
            return pixmap
        
        if role == Qt.BackgroundRole:
            bg_color = QColor(242, 242, 242)
            bg_brush = QBrush(bg_color)
            return bg_color

        if app_constants.GRID_TOOLTIP and role == Qt.ToolTipRole:
            add_bold = []
            add_tips = []
            if app_constants.TOOLTIP_TITLE:
                add_bold.append('<b>Title:</b>')
                add_tips.append(current_gallery.title)
            if app_constants.TOOLTIP_AUTHOR:
                add_bold.append('<b>Author:</b>')
                add_tips.append(current_gallery.artist)
            if app_constants.TOOLTIP_CHAPTERS:
                add_bold.append('<b>Chapters:</b>')
                add_tips.append(len(current_gallery.chapters))
            if app_constants.TOOLTIP_STATUS:
                add_bold.append('<b>Status:</b>')
                add_tips.append(current_gallery.status)
            if app_constants.TOOLTIP_TYPE:
                add_bold.append('<b>Type:</b>')
                add_tips.append(current_gallery.type)
            if app_constants.TOOLTIP_LANG:
                add_bold.append('<b>Language:</b>')
                add_tips.append(current_gallery.language)
            if app_constants.TOOLTIP_DESCR:
                add_bold.append('<b>Description:</b><br />')
                add_tips.append(current_gallery.info)
            if app_constants.TOOLTIP_TAGS:
                add_bold.append('<b>Tags:</b>')
                add_tips.append(utils.tag_to_string(current_gallery.tags))
            if app_constants.TOOLTIP_LAST_READ:
                add_bold.append('<b>Last read:</b>')
                add_tips.append('{} ago'.format(utils.get_date_age(current_gallery.last_read)) if current_gallery.last_read else "Never!")
            if app_constants.TOOLTIP_TIMES_READ:
                add_bold.append('<b>Times read:</b>')
                add_tips.append(current_gallery.times_read)
            if app_constants.TOOLTIP_PUB_DATE:
                add_bold.append('<b>Publication Date:</b>')
                add_tips.append('{}'.format(current_gallery.pub_date).split(' ')[0])
            if app_constants.TOOLTIP_DATE_ADDED:
                add_bold.append('<b>Date added:</b>')
                add_tips.append('{}'.format(current_gallery.date_added).split(' ')[0])

            tooltip = ""
            tips = list(zip(add_bold, add_tips))
            for tip in tips:
                tooltip += "{} {}<br />".format(tip[0], tip[1])
            return tooltip

        if role == self.GALLERY_ROLE:
            return current_gallery

        # favorite satus
        if role == self.FAV_ROLE:
            return current_gallery.fav

        if role == self.DATE_ADDED_ROLE:
            date_added = "{}".format(current_gallery.date_added)
            qdate_added = QDateTime.fromString(date_added, "yyyy-MM-dd HH:mm:ss")
            return qdate_added
        
        if role == self.PUB_DATE_ROLE:
            if current_gallery.pub_date:
                pub_date = "{}".format(current_gallery.pub_date)
                qpub_date = QDateTime.fromString(pub_date, "yyyy-MM-dd HH:mm:ss")
                return qpub_date

        if role == self.TIMES_READ_ROLE:
            return current_gallery.times_read

        if role == self.LAST_READ_ROLE:
            if current_gallery.last_read:
                last_read = "{}".format(current_gallery.last_read)
                qlast_read = QDateTime.fromString(last_read, "yyyy-MM-dd HH:mm:ss")
                return qlast_read

        if role == self.TIME_ROLE:
            return current_gallery.qtime

        if role == self.RATING_ROLE:
            return StarRating(current_gallery.rating)

        return None

    def rowCount(self, index=QModelIndex()):
        if index.isValid():
            return 0
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(app_constants.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section == self._TITLE:
                return 'Title'
            elif section == self._ARTIST:
                return 'Author'
            elif section == self._TAGS:
                return 'Tags'
            elif section == self._TYPE:
                return 'Type'
            elif section == self._FAV:
                return u'\u2605'
            elif section == self._CHAPTERS:
                return 'Chapters'
            elif section == self._LANGUAGE:
                return 'Language'
            elif section == self._LINK:
                return 'Link'
            elif section == self._DESCR:
                return 'Description'
            elif section == self._DATE_ADDED:
                return 'Date Added'
            elif section == self._PUB_DATE:
                return 'Published'
        return section + 1


    def insertRows(self, position, rows, index=QModelIndex()):
        self._data_count += rows
        if not self._gallery_to_add:
            return False

        self.beginInsertRows(QModelIndex(), position, position + rows - 1)
        for r in range(rows):
            self._data.insert(position, self._gallery_to_add.pop())
        self.endInsertRows()
        return True

    def replaceRows(self, list_of_gallery, position, rows=1, index=QModelIndex()):
        "replaces gallery data to the data list WITHOUT adding to DB"
        for pos, gallery in enumerate(list_of_gallery):
            del self._data[position + pos]
            self._data.insert(position + pos, gallery)
        self.dataChanged.emit(index, index, [Qt.UserRole + 1, Qt.DecorationRole])

    def removeRows(self, position, rows, index=QModelIndex()):
        self._data_count -= rows
        self.beginRemoveRows(QModelIndex(), position, position + rows - 1)
        for r in range(rows):
            try:
                self._data.remove(self._gallery_to_remove.pop())
            except ValueError:
                return False
        self.endRemoveRows()
        return True

class BaseModel(QStandardItemModel):

    _fetch_sig = pyqtSignal(QModelIndex)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loader = None
        self._fetching = False
        self._session = db_constants.SESSION()

    def fetch_more(self, idx):
        if not self._fetching:
            self._fetching = True
            self._fetch_sig.emit(idx)

    def append_item(self, idx, dbitem):
        ""
        pitem = None
        item = None
        if isinstance(dbitem, db.Collection):
            pitem = self.invisibleRootItem()
            dbitem.profile = os.path.join(db_constants.THUMBNAIL_PATH, "thumb2.png")
            item = CollectionItem(dbitem)
        elif isinstance(dbitem, db.Gallery):
            item = GalleryItem(dbitem)
            dbitem.profile = os.path.join(db_constants.THUMBNAIL_PATH, "thumb.png")
            pitem = idx.data(app_constants.QITEM_ROLE)
        elif isinstance(dbitem, db.Page):
            item = PageItem(dbitem)
            dbitem.profile = os.path.join(db_constants.THUMBNAIL_PATH, "thumb3.png")
            pitem = idx.data(app_constants.QITEM_ROLE)
        else:
            raise NotImplementedError

        if not dbitem in self._session:
            try:
                self._session.add(dbitem)
            except db.exc.InvalidRequestError:
                self._session.merge(dbitem)

        if pitem and item:
            pitem.appendRow(item)

    def attach_loader(self, loader):
        assert isinstance(loader, ModelDataLoader)
        self._loader = loader
        self._fetch_sig.connect(self._loader.fetch_more)
        self._loader.item_loaded.connect(self.append_item)
        self._loader.finished.connect(lambda: setattr(self, '_fetching', False))
        self._fetch_sig.emit(QModelIndex())

class ViewMetaWindow(misc.ArrowWindow):

    def __init__(self, parent):
        super().__init__(parent)
        # gallery data stuff
        self.content_margin = 10
        self.current_item = None
        self.current_idx = None
        self.view = None
        self.g_widget = self.GalleryLayout(self, parent)
        self.hide_timer = QTimer()
        self.hide_timer.timeout.connect(self.delayed_hide)
        self.hide_timer.setSingleShot(True)
        self.hide_animation = misc.create_animation(self, 'windowOpacity')
        self.hide_animation.setDuration(250)
        self.hide_animation.setStartValue(1.0)
        self.hide_animation.setEndValue(0.0)
        self.hide_animation.finished.connect(self.hide)
        self.show_animation = misc.create_animation(self, 'windowOpacity')
        self.show_animation.setDuration(350)
        self.show_animation.setStartValue(0.0)
        self.show_animation.setEndValue(1.0)
        self.setFocusPolicy(Qt.NoFocus)

    def show(self):
        if not self.hide_animation.Running:
            self.setWindowOpacity(0)
            super().show()
            self.show_animation.start()
        else:
            self.hide_animation.stop()
            super().show()
            self.show_animation.setStartValue(self.windowOpacity())
            self.show_animation.start()

    def focusOutEvent(self, event):
        self.delayed_hide()
        return super().focusOutEvent(event)

    def _mouse_in_item(self):
        if self.current_idx and self.view:
            mouse_p = QCursor.pos()
            h = self.idx_top_l.x() <= mouse_p.x() <= self.idx_top_r.x()
            v = self.idx_top_l.y() <= mouse_p.y() <= self.idx_btm_l.y()
            if h and v:
                return True
        return False

    def mouseMoveEvent(self, event):
        if self.isVisible():
            if not self._mouse_in_item():
                if not self.hide_timer.isActive():
                    self.hide_timer.start(300)
        return super().mouseMoveEvent(event)

    def delayed_hide(self):
        if not self.underMouse() and not self._mouse_in_item():
            self.hide_animation.start()

    def show_item(self, index, view):
        self.resize(app_constants.POPUP_WIDTH, app_constants.POPUP_HEIGHT)
        self.view = view
        desktop_w = QDesktopWidget().width()
        desktop_h = QDesktopWidget().height()
        
        margin_offset = 20 # should be higher than gallery_touch_offset
        gallery_touch_offset = 10 # How far away the window is from touching gallery

        index_rect = view.visualRect(index)
        self.idx_top_l = index_top_left = view.mapToGlobal(index_rect.topLeft())
        self.idx_top_r = index_top_right = view.mapToGlobal(index_rect.topRight())
        self.idx_btm_l = index_btm_left = view.mapToGlobal(index_rect.bottomLeft())
        index_btm_right = view.mapToGlobal(index_rect.bottomRight())

        if app_constants.DEBUG:
            for idx in (index_top_left, index_top_right, index_btm_left, index_btm_right):
                print(idx.x(), idx.y())

        # adjust placement

        def check_left():
            middle = (index_top_left.y() + index_btm_left.y()) / 2 # middle of gallery left side
            left = (index_top_left.x() - self.width() - margin_offset) > 0 # if the width can be there
            top = (middle - (self.height() / 2) - margin_offset) > 0 # if the top half of window can be there
            btm = (middle + (self.height() / 2) + margin_offset) < desktop_h # same as above, just for the bottom
            if left and top and btm:
                self.direction = self.RIGHT
                x = index_top_left.x() - gallery_touch_offset - self.width()
                y = middle - (self.height() / 2)
                appear_point = QPoint(int(x), int(y))
                self.move(appear_point)
                return True
            return False

        def check_right():
            middle = (index_top_right.y() + index_btm_right.y()) / 2 # middle of gallery right side
            right = (index_top_right.x() + self.width() + margin_offset) < desktop_w # if the width can be there
            top = (middle - (self.height() / 2) - margin_offset) > 0 # if the top half of window can be there
            btm = (middle + (self.height() / 2) + margin_offset) < desktop_h # same as above, just for the bottom

            if right and top and btm:
                self.direction = self.LEFT
                x = index_top_right.x() + gallery_touch_offset
                y = middle - (self.height() / 2)
                appear_point = QPoint(int(x), int(y))
                self.move(appear_point)
                return True
            return False

        def check_top():
            middle = (index_top_left.x() + index_top_right.x()) / 2 # middle of gallery top side
            top = (index_top_right.y() - self.height() - margin_offset) > 0 # if the height can be there
            left = (middle - (self.width() / 2) - margin_offset) > 0 # if the left half of window can be there
            right = (middle + (self.width() / 2) + margin_offset) < desktop_w # same as above, just for the right

            if top and left and right:
                self.direction = self.BOTTOM
                x = middle - (self.width() / 2)
                y = index_top_left.y() - gallery_touch_offset - self.height()
                appear_point = QPoint(int(x), int(y))
                self.move(appear_point)
                return True
            return False

        def check_bottom(override=False):
            middle = (index_btm_left.x() + index_btm_right.x()) / 2 # middle of gallery bottom side
            btm = (index_btm_right.y() + self.height() + margin_offset) < desktop_h # if the height can be there
            left = (middle - (self.width() / 2) - margin_offset) > 0 # if the left half of window can be there
            right = (middle + (self.width() / 2) + margin_offset) < desktop_w # same as above, just for the right

            if (btm and left and right) or override:
                self.direction = self.TOP
                x = middle - (self.width() / 2)
                y = index_btm_left.y() + gallery_touch_offset
                appear_point = QPoint(int(x), int(y))
                self.move(appear_point)
                return True
            return False

        for pos in (check_bottom, check_right, check_left, check_top):
            if pos():
                break
        else: # default pos is bottom
            check_bottom(True)

        self._set_item(index.data(app_constants.ITEM_ROLE))
        self.show()

    def closeEvent(self, ev):
        ev.ignore()
        self.delayed_hide()

    def _set_item(self, item):
        self.current_item = item

        if isinstance(item, db.Gallery):
            self.g_widget.apply_gallery(item)
            self.g_widget.resize(self.width() - self.content_margin,
                                         self.height() - self.content_margin)
        if self.direction == self.LEFT:
            start_point = QPoint(self.arrow_size.width(), 0)
        elif self.direction == self.TOP:
            start_point = QPoint(0, self.arrow_size.height())
        else:
            start_point = QPoint(0, 0)
        # title
        #title_region = QRegion(0, 0, self.g_title_lbl.width(),
        #self.g_title_lbl.height())
        self.g_widget.move(start_point)

    class GalleryLayout(QFrame):

        def __init__(self, parent, appwindow):
            super().__init__(parent)
            self.appwindow = appwindow
            self.setStyleSheet('color:white;')
            main_layout = QHBoxLayout(self)
            self.stacked_l = stacked_l = QStackedLayout()
            general_info = QWidget(self)
            self.general_index = stacked_l.addWidget(general_info)
            self.left_layout = QFormLayout()
            self.main_left_layout = QVBoxLayout(general_info)
            self.main_left_layout.addLayout(self.left_layout)
            self.right_layout = QFormLayout()
            main_layout.addLayout(stacked_l, 1)
            main_layout.addWidget(misc.Line('v'))
            main_layout.addLayout(self.right_layout)
            def get_label(txt):
                lbl = QLabel(txt)
                lbl.setWordWrap(True)
                return lbl
            self.g_title_lbl = get_label('')
            self.g_title_lbl.setStyleSheet('color:white;font-weight:bold;')
            self.left_layout.addRow(self.g_title_lbl)
            self.artists_layout = misc.FlowLayout()
            self.left_layout.addRow(self.artists_layout)
            for lbl in (self.g_title_lbl, self.artists_layout):
                lbl.setAlignment(Qt.AlignCenter)
            self.left_layout.addRow(misc.Line('h'))

            first_layout = QHBoxLayout()
            self.g_type_lbl = misc.ClickedLabel()
            self.g_type_lbl.setStyleSheet('text-decoration: underline')
            self.g_type_lbl.clicked.connect(lambda a: appwindow.search("type:{}".format(a)))
            self.g_lang_lbl = misc.ClickedLabel()
            self.g_lang_lbl.setStyleSheet('text-decoration: underline')
            self.g_lang_lbl.clicked.connect(lambda a: appwindow.search("language:{}".format(a)))
            self.right_layout.addRow(self.g_type_lbl)
            self.right_layout.addRow(self.g_lang_lbl)
            #first_layout.addWidget(self.g_lang_lbl, 0, Qt.AlignLeft)
            #first_layout.addWidget(self.g_type_lbl, 0, Qt.AlignRight)
            self.left_layout.addRow(first_layout)

            self.g_status_lbl = QLabel()
            self.g_d_added_lbl = QLabel()
            self.g_pub_lbl = QLabel()
            self.g_last_read_lbl = QLabel()
            self.g_read_count_lbl = QLabel()
            self.g_pages_total_lbl = QLabel()
            self.right_layout.addRow(self.g_read_count_lbl)
            self.right_layout.addRow('Pages:', self.g_pages_total_lbl)
            self.right_layout.addRow('Status:', self.g_status_lbl)
            self.right_layout.addRow('Added:', self.g_d_added_lbl)
            self.right_layout.addRow('Published:', self.g_pub_lbl)
            self.right_layout.addRow('Last read:', self.g_last_read_lbl)

            self.g_info_lbl = get_label('')
            self.left_layout.addRow(self.g_info_lbl)

            self.g_url_lbl = misc.ClickedLabel()
            self.g_url_lbl.clicked.connect(lambda: utils.open_web_link(self.g_url_lbl.text()))
            self.g_url_lbl.setWordWrap(True)
            self.left_layout.addRow('URL:', self.g_url_lbl)
            #self.left_layout.addRow(Line('h'))

            self.tags_scroll = QScrollArea(self)
            self.tags_widget = QWidget(self.tags_scroll)
            self.tags_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.tags_layout = QFormLayout(self.tags_widget)
            self.tags_layout.setSizeConstraint(self.tags_layout.SetMaximumSize)
            self.tags_scroll.setWidget(self.tags_widget)
            self.tags_scroll.setWidgetResizable(True)
            self.tags_scroll.setFrameShape(QFrame.NoFrame)
            self.main_left_layout.addWidget(self.tags_scroll)


        def has_tags(self, tags):
            t_len = len(tags)
            if not t_len:
                return False
            if t_len == 1:
                if 'default' in tags:
                    if not tags['default']:
                        return False
            return True

        def apply_gallery(self, gallery):
            self.stacked_l.setCurrentIndex(self.general_index)
            self.g_title_lbl.setText(gallery.title.name)

            misc.clearLayout(self.artists_layout)
            for artist in gallery.artists:
                g_artist_lbl = misc.ClickedLabel(artist.name)
                g_artist_lbl.setWordWrap(True)
                g_artist_lbl.clicked.connect(lambda a: appwindow.search("artist:{}".format(a)))
                g_artist_lbl.setStyleSheet('color:#bdc3c7;')
                g_artist_lbl.setToolTip("Click to see more from this artist")
                self.artists_layout.addWidget(g_artist_lbl)

            if gallery.type:
                self.g_lang_lbl.setText(gallery.language.name)
            if gallery.type:
                self.g_type_lbl.setText(gallery.type.name)
            #self.g_pages_total_lbl.setText('{}'.format(gallery.pages.count() if gallery.pages else 0))
            #self.g_status_lbl.setText(gallery.status.name)
            if gallery.timestamp:
                self.g_d_added_lbl.setText(gallery.timestamp.strftime('%d %b %Y'))
            if gallery.pub_date:
                self.g_pub_lbl.setText(gallery.pub_date.strftime('%d %b %Y'))
            else:
                self.g_pub_lbl.setText('Unknown')
            last_read_txt = '{} ago'.format(utils.get_date_age(gallery.last_read)) if gallery.last_read else "Never!"
            self.g_last_read_lbl.setText(last_read_txt)
            self.g_read_count_lbl.setText('Read {} times'.format(gallery.times_read))
            self.g_info_lbl.setText(gallery.info)
            if 2 == 1:
                self.g_url_lbl.setText(gallery.urls)
                self.g_url_lbl.show()
            else:
                self.g_url_lbl.hide()

            
            #clearLayout(self.tags_layout)
            #if self.has_tags(gallery.tags):
            #    ns_layout = QFormLayout()
            #    self.tags_layout.addRow(ns_layout)
            #    for namespace in sorted(gallery.tags):
            #        tags_lbls = FlowLayout()
            #        if namespace == 'default':
            #            self.tags_layout.insertRow(0, tags_lbls)
            #        else:
            #            self.tags_layout.addRow(namespace, tags_lbls)

            #        for n, tag in enumerate(sorted(gallery.tags[namespace]), 1):
            #            if namespace == 'default':
            #                t = TagText(search_widget=self.appwindow)
            #            else:
            #                t = TagText(search_widget=self.appwindow, namespace=namespace)
            #            t.setText(tag)
            #            tags_lbls.addWidget(t)
            #            t.setAutoFillBackground(True)
            self.tags_widget.adjustSize()

class DefaultDelegate(QStyledItemDelegate):
    "A custom delegate for the model/view framework"

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if option.state & QStyle.State_Selected:
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(164,164,164,120)))
            painter.drawRoundedRect(option.rect, 5, 5)
            painter.restore()

class GridDelegate(QStyledItemDelegate):
    "A custom delegate for the model/view framework"

    POPUP = pyqtSignal()
    CONTEXT_ON = False

    def __init__(self, app_inst, parent):
        super().__init__(parent)
        QPixmapCache.setCacheLimit(app_constants.THUMBNAIL_CACHE_SIZE[0] * app_constants.THUMBNAIL_CACHE_SIZE[1])
        self._painted_indexes = {}
        self.view = parent
        self.parent_widget = app_inst
        self._paint_level = 99

        self.font_size = app_constants.GALLERY_FONT[1]
        self.font_name = 0 # app_constants.GALLERY_FONT[0]
        if not self.font_name:
            self.font_name = QWidget().font().family()
        self.title_font = QFont()
        self.title_font.setBold(True)
        self.title_font.setFamily(self.font_name)
        self.artist_font = QFont()
        self.artist_font.setFamily(self.font_name)
        if self.font_size is not 0:
            self.title_font.setPixelSize(self.font_size)
            self.artist_font.setPixelSize(self.font_size)
        self.title_font_m = QFontMetrics(self.title_font)
        self.artist_font_m = QFontMetrics(self.artist_font)
        self.W = app_constants.THUMB_W_SIZE
        self.H = app_constants.THUMB_H_SIZE + app_constants.GRIDBOX_LBL_H

    def key(self, key):
        "Assigns an unique key to indexes"
        if key in self._painted_indexes:
            return self._painted_indexes[key]
        else:
            k = str(key)
            self._painted_indexes[key] = k
            return k

    def _increment_paint_level(self):
        self._paint_level += 1
        self.view.update()

    def paint(self, painter, option, index):
        assert isinstance(painter, QPainter)
        rec = option.rect.getRect()
        x = rec[0]
        y = rec[1]
        w = rec[2]
        h = rec[3]

        item = index.data(app_constants.ITEM_ROLE)
        qitem = index.data(app_constants.QITEM_ROLE)
        is_gallery = qitem.type() == GalleryItem.type()
        is_page = qitem.type() == PageItem.type()
        is_collection = qitem.type() == CollectionItem.type()

        if self._paint_level:
            painter.setRenderHint(QPainter.Antialiasing)


            star_rating = StarRating(index.data(app_constants.RATING_ROLE))
            title_color = app_constants.GRID_VIEW_TITLE_COLOR
            artist_color = app_constants.GRID_VIEW_ARTIST_COLOR
            label_color = app_constants.GRID_VIEW_LABEL_COLOR
            title = index.data(Qt.DisplayRole)
            title_text = title.name if is_gallery else title

            if is_gallery:
                artists = index.data(app_constants.ARTIST_ROLE)
                artist = ""
                for n, a in enumerate(artists, 1):
                    artist += a.name
                    if n != len(artists):
                        artist += " & "

                # Enable this to see the defining box
                #painter.drawRect(option.rect)
                # define font size
                if 20 > len(title_text) > 15:
                    title_size = "font-size:{}pt;".format(self.font_size)
                elif 30 > len(title_text) > 20:
                    title_size = "font-size:{}pt;".format(self.font_size - 1)
                elif 40 > len(title_text) >= 30:
                    title_size = "font-size:{}pt;".format(self.font_size - 2)
                elif 50 > len(title_text) >= 40:
                    title_size = "font-size:{}pt;".format(self.font_size - 3)
                elif len(title_text) >= 50:
                    title_size = "font-size:{}pt;".format(self.font_size - 4)
                else:
                    title_size = "font-size:{}pt;".format(self.font_size)

                if 30 > len(artist) > 20:
                    artist_size = "font-size:{}pt;".format(self.font_size)
                elif 40 > len(artist) >= 30:
                    artist_size = "font-size:{}pt;".format(self.font_size - 1)
                elif len(artist) >= 40:
                    artist_size = "font-size:{}pt;".format(self.font_size - 2)
                else:
                    artist_size = "font-size:{}pt;".format(self.font_size)

                text_area = QTextDocument()
                text_area.setDefaultFont(option.font)
                text_area.setHtml("""
                <head>
                <style>
                #area
                {{
                    display:flex;
                    width:{6}pt;
                    height:{7}pt;
                }}
                #title {{
                position:absolute;
                color: {4};
                font-weight:bold;
                {0}
                }}
                #artist {{
                position:absolute;
                color: {5};
                top:20pt;
                right:0;
                {1}
                }}
                </style>
                </head>
                <body>
                <div id="area">
                <center>
                <div id="title">{2}
                </div>
                <div id="artist">{3}
                </div>
                </div>
                </center>
                </body>
                """.format(title_size, artist_size, title_text, artist, title_color, artist_color,
                    130 + app_constants.SIZE_FACTOR, 1 + app_constants.SIZE_FACTOR))
                text_area.setTextWidth(w)

            def center_img(width):
                new_x = x
                if width < w:
                    diff = w - width
                    offset = diff // 2
                    new_x += offset
                return new_x

            def img_too_big(start_x):
                txt_layout = misc.text_layout("Thumbnail regeneration needed!", w, self.title_font, self.title_font_m)

                clipping = QRectF(x, y + h // 4, w, app_constants.GRIDBOX_LBL_H - 10)
                txt_layout.draw(painter, QPointF(x, y + h // 4),
                        clip=clipping)

            loaded_image = index.data(Qt.DecorationRole)
            if loaded_image and self._paint_level > 0 and self.view.scroll_speed < 600:
                # if we can't find a cached image
                pix_cache = QPixmapCache.find(self.key(loaded_image.cacheKey()))
                if isinstance(pix_cache, QPixmap):
                    self.image = pix_cache
                    img_x = center_img(self.image.width())
                    if self.image.width() > w or self.image.height() > h:
                        img_too_big(img_x)
                    else:
                        if self.image.height() < self.image.width(): #to keep aspect ratio
                            painter.drawPixmap(QPoint(img_x,y),
                                    self.image)
                        else:
                            painter.drawPixmap(QPoint(img_x,y),
                                    self.image)
                else:
                    self.image = QPixmap.fromImage(loaded_image)
                    img_x = center_img(self.image.width())
                    QPixmapCache.insert(self.key(loaded_image.cacheKey()), self.image)
                    if self.image.width() > w or self.image.height() > h:
                        img_too_big(img_x)
                    else:
                        if self.image.height() < self.image.width(): #to keep aspect ratio
                            painter.drawPixmap(QPoint(img_x,y),
                                    self.image)
                        else:
                            painter.drawPixmap(QPoint(img_x,y),
                                    self.image)
            else:

                painter.save()
                painter.setPen(QColor(164,164,164,200))
                if loaded_image:
                    thumb_text = "Loading..."
                else:
                    thumb_text = "Thumbnail regeneration needed!"
                txt_layout = misc.text_layout(thumb_text, w, self.title_font, self.title_font_m)

                clipping = QRectF(x, y + h // 4, w, app_constants.GRIDBOX_LBL_H - 10)
                txt_layout.draw(painter, QPointF(x, y + h // 4),
                        clip=clipping)
                painter.restore()

            if is_gallery:
                # draw ribbon type
                painter.save()
                painter.setPen(Qt.NoPen)
                if app_constants.DISPLAY_GALLERY_RIBBON:
                    type_ribbon_w = type_ribbon_l = w * 0.11
                    rib_top_1 = QPointF(x + w - type_ribbon_l - type_ribbon_w, y)
                    rib_top_2 = QPointF(x + w - type_ribbon_l, y)
                    rib_side_1 = QPointF(x + w, y + type_ribbon_l)
                    rib_side_2 = QPointF(x + w, y + type_ribbon_l + type_ribbon_w)
                    ribbon_polygon = QPolygonF([rib_top_1, rib_top_2, rib_side_1, rib_side_2])
                    ribbon_path = QPainterPath()
                    ribbon_path.setFillRule(Qt.WindingFill)
                    ribbon_path.addPolygon(ribbon_polygon)
                    ribbon_path.closeSubpath()
                    painter.setBrush(QBrush(QColor(self._ribbon_color(index.data(app_constants.TYPE_ROLE)))))
                    painter.drawPath(ribbon_path)

                # draw if favourited
                if index.data(app_constants.FAV_ROLE):
                    star_ribbon_w = w * 0.1
                    star_ribbon_l = w * 0.08
                    rib_top_1 = QPointF(x + star_ribbon_l, y)
                    rib_side_1 = QPointF(x, y + star_ribbon_l)
                    rib_top_2 = QPointF(x + star_ribbon_l + star_ribbon_w, y)
                    rib_side_2 = QPointF(x, y + star_ribbon_l + star_ribbon_w)
                    rib_star_mid_1 = QPointF((rib_top_1.x() + rib_side_1.x()) / 2, (rib_top_1.y() + rib_side_1.y()) / 2)
                    rib_star_factor = star_ribbon_l / 4
                    rib_star_p1_1 = rib_star_mid_1 + QPointF(rib_star_factor, -rib_star_factor)
                    rib_star_p1_2 = rib_star_p1_1 + QPointF(-rib_star_factor, -rib_star_factor)
                    rib_star_p1_3 = rib_star_mid_1 + QPointF(-rib_star_factor, rib_star_factor)
                    rib_star_p1_4 = rib_star_p1_3 + QPointF(-rib_star_factor, -rib_star_factor)

                    crown_1 = QPolygonF([rib_star_p1_1, rib_star_p1_2, rib_star_mid_1, rib_star_p1_4, rib_star_p1_3])
                    painter.setBrush(QBrush(QColor(255, 255, 0, 200)))
                    painter.drawPolygon(crown_1)

                    ribbon_polygon = QPolygonF([rib_top_1, rib_side_1, rib_side_2, rib_top_2])
                    ribbon_path = QPainterPath()
                    ribbon_path.setFillRule(Qt.WindingFill)
                    ribbon_path.addPolygon(ribbon_polygon)
                    ribbon_path.closeSubpath()
                    painter.drawPath(ribbon_path)
                    painter.setPen(QColor(255, 0, 0, 100))
                    painter.drawPolyline(rib_top_1, rib_star_p1_1, rib_star_p1_2, rib_star_mid_1, rib_star_p1_4, rib_star_p1_3, rib_side_1)
                    painter.drawLine(rib_top_1, rib_top_2)
                    painter.drawLine(rib_top_2, rib_side_2)
                    painter.drawLine(rib_side_1, rib_side_2)
                painter.restore()

            if self._paint_level > 0:
                type_h = painter.fontMetrics().height()
                type_p = QPoint(x + 4, y + app_constants.THUMB_H_SIZE - type_h - 5)
                if is_gallery or is_page:
                    type_w = painter.fontMetrics().width(item.file_type)
                    type_rect = QRect(type_p.x() - 2, type_p.y() - 1, type_w + 4, type_h + 1)
                    if app_constants.DISPLAY_GALLERY_TYPE:
                        type_color = QColor(239, 0, 0, 200)
                        if item.file_type in ("zip", "jpg"):
                            type_color = QColor(241, 0, 83, 200)
                        elif item.file_type in ("cbz", "png"):
                            type_color = QColor(0, 139, 0, 200)
                        elif item.file_type == "rar":
                            type_color = QColor(30, 127, 150, 200)
                        elif item.file_type == "cbr":
                            type_color = QColor(210, 0, 13, 200)

                        painter.save()
                        painter.setPen(QPen(Qt.white))
                        painter.fillRect(type_rect, type_color)
                        painter.drawText(type_p.x(), type_p.y() + painter.fontMetrics().height() - 4, item.file_type)
                        painter.restore()
                else:
                    type_rect = QRect(type_p.x() - 2, type_p.y() - 1, x, type_h)
                

                if app_constants.DISPLAY_RATING and index.data(app_constants.RATING_ROLE) and (is_gallery or is_collection):
                    star_start_x = type_rect.x()+type_rect.width() if app_constants.DISPLAY_GALLERY_TYPE and is_gallery else x
                    star_width = star_rating.sizeHint().width()
                    star_start_x += ((x+w-star_start_x)-(star_width))/2
                    star_rating.paint(painter,
                        QRect(star_start_x, type_rect.y(), star_width, type_rect.height()))

            #if item.state == app_constants.GalleryState.New:
            #    painter.save()
            #    painter.setPen(Qt.NoPen)
            #    gradient = QLinearGradient()
            #    gradient.setStart(x, y + app_constants.THUMB_H_SIZE / 2)
            #    gradient.setFinalStop(x, y + app_constants.THUMB_H_SIZE)
            #    gradient.setColorAt(0, QColor(255, 255, 255, 0))
            #    gradient.setColorAt(1, QColor(0, 255, 0, 150))
            #    painter.setBrush(QBrush(gradient))
            #    painter.drawRoundedRect(QRectF(x, y + app_constants.THUMB_H_SIZE / 2, w, app_constants.THUMB_H_SIZE / 2), 2, 2)
            #    painter.restore()

            def draw_text_label(lbl_h):
                #draw the label for text
                painter.save()
                painter.translate(x, y + app_constants.THUMB_H_SIZE)
                box_color = QBrush(QColor(label_color))#QColor(0,0,0,123))
                painter.setBrush(box_color)
                rect = QRect(0, 0, w, lbl_h) #x, y, width, height
                painter.fillRect(rect, box_color)
                painter.restore()
                return rect

            if option.state & QStyle.State_MouseOver or \
                option.state & QStyle.State_Selected:

                def draw_text(txt, _width, _font, _fontmetrics):
                    txt_layout = misc.text_layout(txt, _width, _font, _fontmetrics)
                    txt_h = txt_layout.boundingRect().height()
                    return txt_layout, txt_h

                artist_layout = None
                if is_gallery:
                    title_layout, t_h = draw_text(title_text, w, self.title_font, self.title_font_m)
                    artist_layout, a_h = draw_text(artist, w, self.artist_font, self.artist_font_m)
                    txt_height = t_h + a_h
                else:
                    title_layout, txt_height = draw_text(index.data(app_constants.TITLE_ROLE), w, self.title_font, self.title_font_m)

                if app_constants.GALLERY_FONT_ELIDE:
                    lbl_rect = draw_text_label(min(txt_height + 3, app_constants.GRIDBOX_LBL_H))
                else:
                    lbl_rect = draw_text_label(app_constants.GRIDBOX_LBL_H)

                clipping = QRectF(x, y + app_constants.THUMB_H_SIZE, w, app_constants.GRIDBOX_LBL_H - 10)
                painter.setPen(QColor(title_color))
                title_layout.draw(painter, QPointF(x, y + app_constants.THUMB_H_SIZE),
                        clip=clipping)

                if artist_layout:
                    painter.setPen(QColor(artist_color))
                    artist_layout.draw(painter, QPointF(x, y + app_constants.THUMB_H_SIZE + t_h),
                            clip=clipping)
                #painter.fillRect(option.rect, QColor)
            else:
                if app_constants.GALLERY_FONT_ELIDE:
                    t_h = self.title_font_m.height()
                    if is_gallery:
                        a_h = self.artist_font_m.height()
                        text_label_h = a_h + t_h * 2
                    else:
                        text_label_h = t_h * 2

                    lbl_rect = draw_text_label(text_label_h)
                else:
                    lbl_rect = draw_text_label(app_constants.GRIDBOX_LBL_H)
                # draw text
                painter.save()
                alignment = QTextOption(Qt.AlignCenter)
                alignment.setUseDesignMetrics(True)
                title_rect = QRectF(0,0,w, self.title_font_m.height())
                if is_gallery:
                    artist_rect = QRectF(0,self.artist_font_m.height(),w,
                                self.artist_font_m.height())
                painter.translate(x, y + app_constants.THUMB_H_SIZE)
                if not app_constants.GALLERY_FONT_ELIDE and is_gallery:
                    text_area.setDefaultFont(QFont(self.font_name))
                    text_area.drawContents(painter)
                else:
                    painter.setFont(self.title_font)
                    painter.setPen(QColor(title_color))
                    painter.drawText(title_rect,
                                self.title_font_m.elidedText(title_text, Qt.ElideRight, w - 10),
                                alignment)
                    
                    if is_gallery:
                        painter.setPen(QColor(artist_color))
                        painter.setFont(self.artist_font)
                        alignment.setWrapMode(QTextOption.NoWrap)
                        painter.drawText(artist_rect,
                                    self.title_font_m.elidedText(artist, Qt.ElideRight, w - 10),
                                    alignment)
                ##painter.resetTransform()
                painter.restore()

            if option.state & QStyle.State_Selected:
                painter.save()
                selected_rect = QRectF(x, y, w, lbl_rect.height() + app_constants.THUMB_H_SIZE)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(164,164,164,120)))
                painter.drawRoundedRect(selected_rect, 5, 5)
                #painter.fillRect(selected_rect, QColor(164,164,164,120))
                painter.restore()

            def warning(txt):
                painter.save()
                selected_rect = QRectF(x, y, w, lbl_rect.height() + app_constants.THUMB_H_SIZE)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(255,0,0,120)))
                p_path = QPainterPath()
                p_path.setFillRule(Qt.WindingFill)
                p_path.addRoundedRect(selected_rect, 5,5)
                p_path.addRect(x,y, 20, 20)
                p_path.addRect(x + w - 20,y, 20, 20)
                painter.drawPath(p_path.simplified())
                painter.setPen(QColor("white"))
                txt_layout = misc.text_layout(txt, w, self.title_font, self.title_font_m)
                txt_layout.draw(painter, QPointF(x, y + h * 0.3))
                painter.restore()

            #if not index.data(app_constants.ITEM_ROLE).id and self.view.view_type != app_constants.ViewType.Addition:
            #    warning("This gallery does not exist anymore!")
            #elif gallery.dead_link:
            #    warning("Cannot find gallery source!")


            if app_constants.DEBUG or self.view.view_type == app_constants.ViewType.Duplicate:
                painter.save()
                painter.setPen(QPen(Qt.white))
                id_txt = "ID: {}".format(index.data(app_constants.ITEM_ROLE).id)
                type_w = painter.fontMetrics().width(id_txt)
                type_h = painter.fontMetrics().height()
                type_p = QPoint(x + 4, y + 50 - type_h - 5)
                type_rect = QRect(type_p.x() - 2, type_p.y() - 1, type_w + 4, type_h + 1)
                painter.fillRect(type_rect, QColor(239, 0, 0, 200))
                painter.drawText(type_p.x(), type_p.y() + painter.fontMetrics().height() - 4, id_txt)
                painter.restore()

            if option.state & QStyle.State_Selected:
                painter.setPen(QPen(option.palette.highlightedText().color()))
        else:
            painter.fillRect(option.rect, QColor(164,164,164,100))
            painter.setPen(QColor(164,164,164,200))
            txt_layout = misc.text_layout("Fetching...", w, self.title_font, self.title_font_m)

            clipping = QRectF(x, y + h // 4, w, app_constants.GRIDBOX_LBL_H - 10)
            txt_layout.draw(painter, QPointF(x, y + h // 4),
                    clip=clipping)

    def _ribbon_color(self, gallery_type):
        if not gallery_type:
            return
        gallery_type = gallery_type.name
        if gallery_type:
            gallery_type = gallery_type.lower()
        if gallery_type == "manga":
            return app_constants.GRID_VIEW_T_MANGA_COLOR
        elif gallery_type == "doujinshi":
            return app_constants.GRID_VIEW_T_DOUJIN_COLOR
        elif "artist cg" in gallery_type:
            return app_constants.GRID_VIEW_T_ARTIST_CG_COLOR
        elif "game cg" in gallery_type:
            return app_constants.GRID_VIEW_T_GAME_CG_COLOR
        elif gallery_type == "western":
            return app_constants.GRID_VIEW_T_WESTERN_COLOR
        elif "image" in gallery_type:
            return app_constants.GRID_VIEW_T_IMAGE_COLOR
        elif gallery_type == "non-h":
            return app_constants.GRID_VIEW_T_NON_H_COLOR
        elif gallery_type == "cosplay":
            return app_constants.GRID_VIEW_T_COSPLAY_COLOR
        else:
            return app_constants.GRID_VIEW_T_OTHER_COLOR

    def sizeHint(self, option, index):
        return QSize(self.W, self.H)

class BaseView(QListView):
    """
    Grid View
    """

    STATUS_BAR_MSG = pyqtSignal(str)

    def __init__(self, model, v_type, filter_model=None, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.view_type = v_type
        # all items have the same size (perfomance)
        self.setUniformItemSizes(True)
        # improve scrolling
        self.setEditTriggers(self.NoEditTriggers)
        self.setAutoScroll(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLayoutMode(self.Batched)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        #self.setDragEnabled(True)
        self.viewport().setAcceptDrops(True)
        #self.setDropIndicatorShown(True)
        self.setDragDropMode(self.DragDrop)
        self.filter_model = filter_model if filter_model else SortFilterModel(self)
        self.setSelectionBehavior(self.SelectItems)
        self.setSelectionMode(self.ExtendedSelection)
        self.base_model = model
        self.filter_model.change_model(self.base_model)
        #self.sort_model.sort(0)
        self.setModel(self.filter_model)
        self.setViewportMargins(0,0,0,0)

        self.item_window = ViewMetaWindow(parent if parent else self)
        self.item_window.arrow_size = (10,10,)
        self.clicked.connect(lambda idx: self.item_window.show_item(idx, self))

        if app_constants.DEBUG:
            def debug_print(a):
                g = a.data(app_constants.ITEM_ROLE)
                try:
                    print("\n",hash(g))
                except:
                    print("{}".format(g).encode(errors='ignore'))
                #log_d(gallerydb.HashDB.gen_gallery_hash(g, 0, 'mid')['mid'])

            self.clicked.connect(debug_print)

        self.k_scroller = QScroller.scroller(self)
        self._scroll_speed_timer = QTimer(self)
        self._scroll_speed_timer.timeout.connect(self._calculate_scroll_speed)
        self._scroll_speed_timer.setInterval(500) # ms
        self._old_scroll_value = 0
        self._scroll_zero_once = True
        self._scroll_speed = 0
        self._scroll_speed_timer.start()

    @property
    def scroll_speed(self):
        return self._scroll_speed

    def _calculate_scroll_speed(self):
        new_value = self.verticalScrollBar().value()
        self._scroll_speed = abs(self._old_scroll_value - new_value)
        self._old_scroll_value = new_value
        
        if self.verticalScrollBar().value() in (0, self.verticalScrollBar().maximum()):
            self._scroll_zero_once = True

        if self._scroll_zero_once:
            self.update()
            self._scroll_zero_once = False

        # update view if not scrolling
        if new_value < 400 and self._old_scroll_value > 400:
            self.update()

    def refresh(self):
        pass

    def get_visible_indexes(self, column=0):
        "find all galleries in viewport"
        gridW = self.grid_delegate.W + app_constants.GRID_SPACING * 2
        gridH = self.grid_delegate.H + app_constants.GRID_SPACING * 2
        region = self.viewport().visibleRegion()
        idx_found = []

        def idx_is_visible(idx):
            idx_rect = self.visualRect(idx)
            return region.contains(idx_rect) or region.intersects(idx_rect)

        #get first index
        first_idx = self.indexAt(QPoint(gridW // 2, 0)) # to get indexes on the way out of view
        if not first_idx.isValid():
            first_idx = self.indexAt(QPoint(gridW // 2, gridH // 2))

        if first_idx.isValid():
            nxt_idx = first_idx
            # now traverse items until index isn't visible
            while(idx_is_visible(nxt_idx)):
                idx_found.append(nxt_idx)
                nxt_idx = nxt_idx.sibling(nxt_idx.row() + 1, column)
            
        return idx_found

    def wheelEvent(self, event):
        if self.item_window.isVisible():
            self.item_window.hide_animation.start()
        return super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        self.item_window.mouseMoveEvent(event)
        return super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Return:
            s_idx = self.selectedIndexes()
            if s_idx:
                for idx in s_idx:
                    self.doubleClicked.emit(idx)
        elif event.modifiers() == Qt.ShiftModifier and event.key() == Qt.Key_Delete:
            CommonView.remove_selected(self, True)
        elif event.key() == Qt.Key_Delete:
            CommonView.remove_selected(self)
        return super().keyPressEvent(event)

    def favorite(self, index):
        assert isinstance(index, QModelIndex)
        gallery = index.data(Qt.UserRole + 1)
        if gallery.fav == 1:
            gallery.fav = 0
            #self.model().replaceRows([gallery], index.row(), 1, index)
            gallerydb.execute(gallerydb.GalleryDB.modify_gallery, True, gallery.id, {'fav':0})
            self.base_model.CUSTOM_STATUS_MSG.emit("Unfavorited")
        else:
            gallery.fav = 1
            #self.model().replaceRows([gallery], index.row(), 1, index)
            gallerydb.execute(gallerydb.GalleryDB.modify_gallery, True, gallery.id, {'fav':1})
            self.base_model.CUSTOM_STATUS_MSG.emit("Favorited")

    def del_chapter(self, index, chap_numb):
        gallery = index.data(Qt.UserRole + 1)
        if len(gallery.chapters) < 2:
            CommonView.remove_gallery(self, [index])
        else:
            msgbox = QMessageBox(self)
            msgbox.setText('Are you sure you want to delete:')
            msgbox.setIcon(msgbox.Question)
            msgbox.setInformativeText('Chapter {} of {}'.format(chap_numb + 1,
                                                          gallery.title))
            msgbox.setStandardButtons(msgbox.Yes | msgbox.No)
            if msgbox.exec() == msgbox.Yes:
                gallery.chapters.pop(chap_numb, None)
                self.base_model.replaceRows([gallery], index.row())
                gallerydb.execute(gallerydb.ChapterDB.del_chapter, True, gallery.id, chap_numb)

    def contextMenuEvent(self, event):
        CommonView.contextMenuEvent(self, event)

    def updateGeometries(self):
        super().updateGeometries()
        self.verticalScrollBar().setSingleStep(app_constants.SCROLL_SPEED)

class GridView(BaseView):
    def __init__(self, model, v_type, filter_model=None, parent=None):
        super().__init__(model, v_type, filter_model, parent)
        self.setViewMode(self.IconMode)
        self.setWrapping(True)
        self.setVerticalScrollMode(self.ScrollPerPixel)
        self.setSpacing(app_constants.GRID_SPACING)
        self.grid_delegate = GridDelegate(parent, self)
        self.setItemDelegate(self.grid_delegate)

class ListView(BaseView):
    def __init__(self, model, v_type, filter_model=None, parent=None):
        super().__init__(model, v_type, filter_model, parent)
        self.setViewMode(self.ListMode)
        self.setAlternatingRowColors(True)

class CommonView:
    """
    Contains identical view implentations
    """

    @staticmethod
    def remove_selected(view_cls, source=False):
        s_indexes = []
        if isinstance(view_cls, QListView):
            s_indexes = view_cls.selectedIndexes()
        elif isinstance(view_cls, QTableView):
            s_indexes = view_cls.selectionModel().selectedRows()

        CommonView.remove_gallery(view_cls, s_indexes, source)

    @staticmethod
    def remove_gallery(view_cls, index_list, local=False):
        #view_cls.sort_model.setDynamicSortFilter(False)
        msgbox = QMessageBox(view_cls)
        msgbox.setIcon(msgbox.Question)
        msgbox.setStandardButtons(msgbox.Yes | msgbox.No)
        if len(index_list) > 1:
            if not local:
                msg = 'Are you sure you want to remove {} selected galleries?'.format(len(index_list))
            else:
                msg = 'Are you sure you want to remove {} selected galleries and their files/directories?'.format(len(index_list))

            msgbox.setText(msg)
        else:
            if not local:
                msg = 'Are you sure you want to remove this gallery?'
            else:
                msg = 'Are you sure you want to remove this gallery and its file/directory?'
            msgbox.setText(msg)

        if msgbox.exec() == msgbox.Yes:
            #view_cls.setUpdatesEnabled(False)
            gallery_list = []
            gallery_db_list = []
            log_i('Removing {} galleries'.format(len(index_list)))
            for index in index_list:
                gallery = index.data(Qt.UserRole + 1)
                gallery_list.append(gallery)
                log_i('Attempt to remove: {} by {}'.format(gallery.title.encode(errors="ignore"),
                                            gallery.artist.encode(errors="ignore")))
                if gallery.id:
                    gallery_db_list.append(gallery)
            gallerydb.execute(gallerydb.GalleryDB.del_gallery, True, gallery_db_list, local=local, priority=0)

            rows = len(gallery_list)
            view_cls.base_model._gallery_to_remove.extend(gallery_list)
            view_cls.base_model.removeRows(view_cls.base_model.rowCount() - rows, rows)

            #view_cls.STATUS_BAR_MSG.emit('Gallery removed!')
            #view_cls.setUpdatesEnabled(True)
        #view_cls.sort_model.setDynamicSortFilter(True)

    @staticmethod
    def find_index(view_cls, gallery_id, sort_model=False):
        "Finds and returns the index associated with the gallery id"
        index = None
        model = view_cls.filter_model if sort_model else view_cls.base_model
        rows = model.rowCount()
        for r in range(rows):
            indx = model.index(r, 0)
            m_gallery = indx.data(Qt.UserRole + 1)
            if m_gallery.id == gallery_id:
                index = indx
                break
        return index

    @staticmethod
    def open_random_gallery(view_cls):
        try:
            g = random.randint(0, view_cls.filter_model.rowCount() - 1)
        except ValueError:
            return
        indx = view_cls.filter_model.index(g, 1)
        chap_numb = 0
        if app_constants.OPEN_RANDOM_GALLERY_CHAPTERS:
            gallery = indx.data(Qt.UserRole + 1)
            b = len(gallery.chapters)
            if b > 1:
                chap_numb = random.randint(0, b - 1)

        CommonView.scroll_to_index(view_cls, view_cls.filter_model.index(indx.row(), 0))
        indx.data(Qt.UserRole + 1).chapters[chap_numb].open()

    @staticmethod
    def scroll_to_index(view_cls, idx, select=True):
        old_value = view_cls.verticalScrollBar().value()
        view_cls.setAutoScroll(False)
        view_cls.setUpdatesEnabled(False)
        view_cls.verticalScrollBar().setValue(0)
        idx_rect = view_cls.visualRect(idx)
        view_cls.verticalScrollBar().setValue(old_value)
        view_cls.setUpdatesEnabled(True)
        rect = QRectF(idx_rect)
        if app_constants.DEBUG:
            print("Scrolling to index:", rect.getRect())
        view_cls.k_scroller.ensureVisible(rect, 0, 0)
        if select:
            view_cls.setCurrentIndex(idx)
        view_cls.setAutoScroll(True)
        view_cls.update()

    @staticmethod
    def contextMenuEvent(view_cls, event):
        grid_view = False
        table_view = False
        if isinstance(view_cls, QListView):
            grid_view = True
        elif isinstance(view_cls, QTableView):
            table_view = True

        handled = False
        index = view_cls.indexAt(event.pos())
        index = view_cls.filter_model.mapToSource(index)

        selected = False
        if table_view:
            s_indexes = view_cls.selectionModel().selectedRows()
        else:
            s_indexes = view_cls.selectedIndexes()
        select_indexes = []
        for idx in s_indexes:
            if idx.isValid() and idx.column() == 0:
                select_indexes.append(view_cls.filter_model.mapToSource(idx))
        if len(select_indexes) > 1:
            selected = True

        if index.isValid():
            if grid_view:
                if view_cls.item_window.isVisible():
                    view_cls.item_window.hide_animation.start()
                view_cls.grid_delegate.CONTEXT_ON = True
            if selected:
                menu = misc.BaseViewMenu(view_cls, index, view_cls.parent_widget, select_indexes)
            else:
                menu = misc.BaseViewMenu(view_cls, index, view_cls.parent_widget)
            menu.delete_items.connect(lambda s: CommonView.remove_gallery(view_cls, select_indexes, s))
            menu.edit_item.connect(CommonView.spawn_dialog)
            handled = True

        if handled:
            menu.exec_(event.globalPos())
            if grid_view:
                view_cls.grid_delegate.CONTEXT_ON = False
            event.accept()
            del menu
        else:
            event.ignore()

    @staticmethod
    def spawn_dialog(app_inst, gallery=None):
        dialog = gallerydialog.GalleryDialog(app_inst, gallery)
        dialog.show()

class GalleryWindow(QFrame):
    
    def __init__(self, parent=None):
        super().__init__(parent)

class PathView(QWidget):

    HEIGHT = 22

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        top_layout = QHBoxLayout()

        persistent_layout = QHBoxLayout()
        top_layout.addLayout(persistent_layout)

        self.home_btn = QPushButton(app_constants.HOME_ICON, "")
        self.home_btn.clicked.connect(lambda: self.update_path(QModelIndex()))
        self.home_btn.adjustSize()
        self.home_btn.setFixedSize(self.home_btn.width(), self.HEIGHT)
        self.home_btn.setStyleSheet("border:0; border-radius:0;")
        persistent_layout.addWidget(self.home_btn)

        self.path_layout = QHBoxLayout()
        top_layout.addLayout(self.path_layout, 1)
        self.path_layout.setAlignment(Qt.AlignLeft)
        main_layout.addLayout(top_layout)

        self.gallery_window = GalleryWindow(self)
        self.gallery_window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.gallery_window)
        main_layout.addWidget(misc.Line("h"))

        self.g_window_slide = misc.create_animation(self.gallery_window, "maximumHeight")
        self.g_window_slide.setEasingCurve(QEasingCurve.InOutQuad)
        self.g_window_slide.setStartValue(0)
        self.g_window_slide.setEndValue(app_constants.THUMB_H_SIZE+app_constants.GRIDBOX_LBL_H//2)

        main_layout.addWidget(view)
        self.install_to_view(view)
        self.gallery_window.hide()

        self.context_bar = gallerydialog.ContextBar(self)
        main_layout.addWidget(self.context_bar)


    def show_g_window(self):
        if not self.gallery_window.isVisible():
            self.g_window_slide.setDirection(self.g_window_slide.Forward)
            self.gallery_window.show()
            try:
                self.g_window_slide.finished.disconnect()
            except TypeError:
                pass
            self.g_window_slide.start()

    def hide_g_window(self):
        if self.gallery_window.isVisible():
            self.g_window_slide.setDirection(self.g_window_slide.Backward)
            self.g_window_slide.finished.connect(self.gallery_window.hide)
            self.g_window_slide.start()


    def add_arrow(self):
        arrow = QPushButton(app_constants.ARROW_RIGHT_ICON, "")
        arrow.setDisabled(True)
        arrow.setStyleSheet("border:0; border-radius:0;")
        arrow.adjustSize()
        arrow.setFixedWidth(arrow.width())
        arrow.setFixedHeight(self.HEIGHT)
        arrow.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.path_layout.insertWidget(0, arrow, Qt.AlignLeft)

    def add_item(self, idx):
        txt = idx.data(Qt.DisplayRole)
        if idx.data(app_constants.QITEM_ROLE).type() == GalleryItem.type():
            txt = txt.name
        path_bar = QPushButton(txt)
        path_bar.setStyleSheet("border:0; border-radius:0;")
        path_bar.setFixedHeight(self.HEIGHT)
        path_bar.adjustSize()
        path_bar.setFixedWidth(path_bar.width())
        path_bar.clicked.connect(lambda: self.view.doubleClicked.emit(idx))
        
        self.path_layout.insertWidget(0, path_bar, Qt.AlignLeft)
        return path_bar

    def update_path(self, idx, toogle_window=True):
        item_type = idx.data(app_constants.QITEM_ROLE)
        if item_type:
            item_type = item_type.type()
        if idx.isValid() and item_type in (GalleryItem.type(), PageItem.type()):
            self.show_g_window()
            # TODO: apply gallery to gallery_window here
        else:
            self.hide_g_window()

        if item_type != PageItem.type():
            if idx.isValid():
                self.view.base_model.fetch_more(idx)
            self.view.setRootIndex(idx)
        if hasattr(self.view, "item_window"):
            self.view.item_window.delayed_hide()
        misc.clearLayout(self.path_layout)

        parent = idx
        _last_path = None
        while parent.isValid():
            if parent.data(app_constants.QITEM_ROLE).type() != PageItem.type():
                pbar = self.add_item(parent)
                if not _last_path:
                    _last_path = pbar
                self.add_arrow()
            parent = parent.parent()
        if _last_path:
            _last_path.setDisabled(True)
        
        if item_type == CollectionItem.type():
            self.context_bar.setContext(self.context_bar.Context.Gallery)
        elif item_type == GalleryItem.type():
            self.context_bar.setContext(self.context_bar.Context.Page)
        else:
            self.context_bar.setContext(self.context_bar.Context.Collection)

    def install_to_view(self, view):
        view.doubleClicked.connect(self.update_path)

    def delegate_for_item(self, itemtype):
        pass

class ViewManager:

    gallery_views = []
    
    @enum.unique
    class View(enum.Enum):
        Grid = 1
        List = 2

    def __init__(self, v_type, parent, allow_sidebarwidget=False):
        self.allow_sidebarwidget = allow_sidebarwidget
        self._delete_proxy_model = None

        self.view_type = v_type

        if v_type == app_constants.ViewType.Default:
            model = GalleryModel(app_constants.GALLERY_DATA, parent)
        elif v_type == app_constants.ViewType.Addition:
            model = GalleryModel(app_constants.GALLERY_ADDITION_DATA, parent)
        elif v_type == app_constants.ViewType.Duplicate:
            model = GalleryModel([], parent)

        self.item_model = self.create_model(None)
        self.grid_view = GridView(self.item_model, v_type, parent=parent)
        self.list_view = ListView(self.item_model, v_type, parent=parent)
        #self.list_view.sort_model.setup_search()
        self.filter_model = self.grid_view.filter_model

        self.view_layout = QStackedLayout()
        self.grid_view_index = self.view_layout.addWidget(PathView(self.grid_view))
        self.list_view_index = self.view_layout.addWidget(PathView(self.list_view))

        self.current_view = self.View.Grid
        self.gallery_views.append(self)

        if v_type in (app_constants.ViewType.Default, app_constants.ViewType.Addition):
            self.filter_model.enable_drag = True

        self.current_sort = app_constants.CURRENT_SORT
        self.current_sort_order = Qt.DescendingOrder
        self.sort(self.current_sort)

    def create_model(self, modeldatatype):
        model = BaseModel()
        loader = ModelDataLoader(modeldatatype)
        model.attach_loader(loader)
        return model

    def _delegate_delete(self):
        if self._delete_proxy_model:
            gs = [g for g in self.item_model._gallery_to_remove]
            self._delete_proxy_model._gallery_to_remove = gs
            self._delete_proxy_model.removeRows(self._delete_proxy_model.rowCount() - len(gs), len(gs))

    def set_delete_proxy(self, other_model):
        self._delete_proxy_model = other_model
        self.item_model.rowsAboutToBeRemoved.connect(self._delegate_delete, Qt.DirectConnection)

    def add_gallery(self, gallery, db=False, record_time=False):
        if isinstance(gallery, (list, tuple)):
            for g in gallery:
                g.view = self.view_type
                if self.view_type != app_constants.ViewType.Duplicate:
                    g.state = app_constants.GalleryState.New
                if db:
                    gallerydb.execute(gallerydb.GalleryDB.add_gallery, True, g)
                else:
                    if not g.profile:
                        Executors.generate_thumbnail(g, on_method=g.set_profile)
            rows = len(gallery)
            self.grid_view.base_model._gallery_to_add.extend(gallery)
            if record_time:
                g.qtime = QTime.currentTime()
        else:
            gallery.view = self.view_type
            if self.view_type != app_constants.ViewType.Duplicate:
                gallery.state = app_constants.GalleryState.New
            rows = 1
            self.grid_view.base_model._gallery_to_add.append(gallery)
            if record_time:
                g.qtime = QTime.currentTime()
            if db:
                gallerydb.execute(gallerydb.GalleryDB.add_gallery, True, gallery)
            else:
                if not gallery.profile:
                    Executors.generate_thumbnail(gallery, on_method=gallery.set_profile)
        self.grid_view.base_model.insertRows(self.grid_view.base_model.rowCount(), rows)
        
    def replace_gallery(self, list_of_gallery, db_optimize=True):
        "Replaces the view and DB with given list of gallery, at given position"
        assert isinstance(list_of_gallery, (list, gallerydb.Gallery)), "Please pass a gallery to replace with"
        if isinstance(list_of_gallery, gallerydb.Gallery):
            list_of_gallery = [list_of_gallery]
        log_d('Replacing {} galleries'.format(len(list_of_gallery)))
        if db_optimize:
            gallerydb.execute(gallerydb.GalleryDB.begin, True)
        for gallery in list_of_gallery:
            kwdict = {'title':gallery.title,
             'profile':gallery.profile,
             'artist':gallery.artist,
             'info':gallery.info,
             'type':gallery.type,
             'language':gallery.language,
             'rating':gallery.rating,
             'status':gallery.status,
             'pub_date':gallery.pub_date,
             'tags':gallery.tags,
             'link':gallery.link,
             'series_path':gallery.path,
             'chapters':gallery.chapters,
             'exed':gallery.exed}

            gallerydb.execute(gallerydb.GalleryDB.modify_gallery,
                             True, gallery.id, **kwdict)
        if db_optimize:
            gallerydb.execute(gallerydb.GalleryDB.end, True)

    def changeTo(self, idx):
        "change view"
        r_itemidx = self.view_layout.currentWidget().view.rootIndex()
        self.view_layout.setCurrentIndex(idx)
        if idx == self.grid_view_index:
            self.current_view = self.View.Grid
        elif idx == self.list_view_index:
            self.current_view = self.View.List
        self.view_layout.currentWidget().update_path(r_itemidx)

    def get_current_view(self):
        if self.current_view == self.View.Grid:
            return self.grid_view
        else:
            return self.list_view

    def sort_order(self, qt_order):
        self.current_sort_order = qt_order
        self.filter_model.sort(0, qt_order)

    def sort(self, name):
        if not self.view_type == app_constants.ViewType.Duplicate:
            if name == 'title':
                self.filter_model.setSortRole(Qt.DisplayRole)
                self.sort_order(Qt.AscendingOrder)
                self.current_sort = 'title'
            elif name == 'artist':
                self.filter_model.setSortRole(GalleryModel.ARTIST_ROLE)
                self.sort_order(Qt.AscendingOrder)
                self.current_sort = 'artist'
            elif name == 'date_added':
                self.filter_model.setSortRole(GalleryModel.DATE_ADDED_ROLE)
                self.sort_order(Qt.DescendingOrder)
                self.current_sort = 'date_added'
            elif name == 'pub_date':
                self.filter_model.setSortRole(GalleryModel.PUB_DATE_ROLE)
                self.sort_order(Qt.DescendingOrder)
                self.current_sort = 'pub_date'
            elif name == 'times_read':
                self.filter_model.setSortRole(GalleryModel.TIMES_READ_ROLE)
                self.sort_order(Qt.DescendingOrder)
                self.current_sort = 'times_read'
            elif name == 'last_read':
                self.filter_model.setSortRole(GalleryModel.LAST_READ_ROLE)
                self.sort_order(Qt.DescendingOrder)
                self.current_sort = 'last_read'

    def set_fav(self, f):
        if not isinstance(self.get_current_view().model(), SortFilterModel):
            return
        if f:
            self.get_current_view().model().fav_view()
        else:
            self.get_current_view().model().catalog_view()

    def fav_is_current(self):
        if self.list_view.filter_model.current_view == \
            self.list_view.filter_model.CAT_VIEW:
            return False
        return True

    def hide(self):
        self.view_layout.currentWidget().hide()

    def show(self):
        self.view_layout.currentWidget().show()

if __name__ == '__main__':
    raise NotImplementedError("Unit testing not yet implemented")
