import datetime
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.tools import bulkloader

class CommentRecord(db.Model):
    user = db.UserProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    text = db.StringProperty(multiline=True)

class GameRecord(db.Model):
    ladder = db.StringProperty()
    winner = db.UserProperty()
    loser = db.UserProperty()
    tie = db.BooleanProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    winner_score = db.IntegerProperty()
    loser_score = db.IntegerProperty()
    comments = db.ListProperty(db.Key)

class UserRecord(db.Model):
    ladder = db.StringProperty()
    user = db.UserProperty()
    nickname = db.StringProperty()
    rating = db.IntegerProperty()
    ratingChange = db.IntegerProperty()

class GameExporter(bulkloader.Exporter):
  def __init__(self):
    bulkloader.Exporter.__init__(self, 'GameRecord',
                                 [('ladder', str, None),
                                  ('winner', str, None),
                                  ('loser', str, None),
                                  ('tie', str, None),
                                  ('date', str, None),
                                  ('winner_score', str, None),
                                  ('loser_score', str, None),
                                  ('comments', str, None)
                                 ])

class GameLoader(bulkloader.Loader):
  def __init__(self):
    bulkloader.Loader.__init__(self, 'GameRecord',
                                [('ladder', str),
                                 ('winner', users.User),
                                 ('loser', users.User),
                                 ('tie', bool),
                                 ('date', lambda x: datetime.datetime.strptime(x,'%Y-%m-%d %H:%M:%S')),
                                 ('winner_score', int),
                                 ('loser_score', int),
                                 ('comments', lambda x: [])
                                ])

class CommentExporter(bulkloader.Exporter):
  def __init__(self):
    bulkloader.Exporter.__init__(self, 'CommentRecord',
                                 [('user', str, None),
                                  ('date', str, None),
                                  ('text', str, None)
                                 ])

class UserExporter(bulkloader.Exporter):
  def __init__(self):
    bulkloader.Exporter.__init__(self, 'UserRecord',
                                 [('ladder', str, None),
                                  ('user', str, None),
                                  ('nickname', str, None),
                                  ('rating', str, None),
                                  ('ratingChange', str, None)
                                 ])

class UserLoader(bulkloader.Loader):
  def __init__(self):
    bulkloader.Loader.__init__(self, 'UserRecord',
                                 [('ladder', str),
                                  ('user', users.User),
                                  ('nickname', str),
                                  ('rating', int),
                                  ('ratingChange', int)
                                 ])

exporters = [CommentExporter, GameExporter, UserExporter]
loaders = [GameLoader, UserLoader]
