"""Incremental queue updates preserve scrolling and delegate identity in QML."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class EpisodeListModel(QAbstractListModel):
    ItemRole = Qt.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def roleNames(self):
        return {self.ItemRole: b'modelData'}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if index.isValid() and role == self.ItemRole and 0 <= index.row() < len(self.rows):
            return self.rows[index.row()]
        return None

    def sync(self, rows):
        desired = {row['id'] for row in rows}
        for index in range(len(self.rows)-1, -1, -1):
            if self.rows[index]['id'] not in desired:
                self.beginRemoveRows(QModelIndex(), index, index)
                self.rows.pop(index)
                self.endRemoveRows()
        for index, row in enumerate(rows):
            if index >= len(self.rows) or self.rows[index]['id'] != row['id']:
                source=next((i for i in range(index+1,len(self.rows)) if self.rows[i]['id']==row['id']),None)
                if source is not None:
                    self.beginMoveRows(QModelIndex(),source,source,QModelIndex(),index)
                    self.rows.insert(index,self.rows.pop(source));self.endMoveRows()
                    if self.rows[index]!=row:
                        self.rows[index]=dict(row);target=self.index(index,0);self.dataChanged.emit(target,target,[self.ItemRole])
                else:
                    self.beginInsertRows(QModelIndex(), index, index)
                    self.rows.insert(index, dict(row))
                    self.endInsertRows()
            elif self.rows[index] != row:
                self.rows[index] = dict(row)
                target = self.index(index, 0)
                self.dataChanged.emit(target, target, [self.ItemRole])
