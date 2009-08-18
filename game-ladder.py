import cgi
import os
import gviz_api
import math
import logging

from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db

ELO_DEFAULT_RATING = 1500
ELO_MATCH_WEIGHT = 50.0
ELO_DIVIDE_FACTOR = 400.0

ladder_name = "fifadev"

# ------------------- Utility Functions ----------------------------------------------------------------------------------
# safe conversion from string -> int, 0 if fails
def int_safe(n):
    try:
        val = int(n)
    except:
        val = 0
    return val

def GetUserRecord(user):
    user = UserRecord.gql("WHERE user = :1", user).get()
    return user

def GetCurrentLadder(self):
    return self.request.path

# ------------------- db Models ----------------------------------------------------------------------------------
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
    winner_team = db.StringProperty()
    loser_team = db.StringProperty()
    comments = db.ListProperty(db.Key)

    def get_comments(self):
        return [ db.get( comment ) for comment in self.comments ]

class UserRecord(db.Model):
    ladder = db.StringProperty()
    user = db.UserProperty()
    nickname = db.StringProperty()
    rating = db.IntegerProperty()
    ratingChange = db.IntegerProperty()

class LadderRecord(db.Model):
    ladder = db.StringProperty()
    date = db.DateTimeProperty(auto_now_add=True)

# ------------------- Helper classes ----------------------------------------------------------------------------------
# get player wins/losses by reading game records
class UserStats:
    def __init__(self, user):
        winQuery = GameRecord.all().filter("ladder =", ladder_name).filter("winner =", user)
        loseQuery = GameRecord.all().filter("ladder =", ladder_name).filter("loser =", user)
        winDrawQuery = GameRecord.all().filter("ladder =", ladder_name).filter("winner =", user).filter("tie =", True)
        loseDrawQuery = GameRecord.all().filter("ladder =", ladder_name).filter("loser =", user).filter("tie =", True)
        winDraw = winDrawQuery.count()
        loseDraw = loseDrawQuery.count()
        self.wins = winQuery.count() - winDraw
        self.losses = loseQuery.count() - loseDraw
        self.draws = winDraw + loseDraw
        self.goalsfor = 0
        self.goalsagainst = 0
        for game in winQuery.fetch(1000):
            self.goalsfor += game.winner_score
            self.goalsagainst += game.loser_score
        for game in loseQuery.fetch(1000):
            self.goalsfor += game.loser_score
            self.goalsagainst += game.winner_score

# ------------------- Elo Rating Functions ---------------------------------------------------------------------------
# based on formula taken from World Football Elo Rating System at eloratings.net
#       Rn = Ro + K x (W - We)
# where Rn is the new rating
#       Ro is the old (pre-match) rating
#       K is match weight
#       W is result of game (1 for a win, 0.5 for a draw, and 0 for a loss)
#       We is expected Result
#
def CalcExpectedResult(playerRating, opponentRating):
    expectedResult = 1.0 / (1.0 + pow(10, (opponentRating - playerRating) / ELO_DIVIDE_FACTOR ))
    return expectedResult

def CalcMatchWeight(goalDifference):
    weight = ELO_MATCH_WEIGHT
    if goalDifference >= 4:
        weight *= 1.75 + (goalDifference - 3) / 8.0
    elif goalDifference >= 3:
        weight *= 1.75
    elif goalDifference >= 2:
        weight *= 1.5
    return weight

def CalcRatingChange(playerRating, opponentRating, result, goalDifference):
    matchWeight = CalcMatchWeight(goalDifference)
    expectedResult = CalcExpectedResult(playerRating, opponentRating)
    resultDiff = result - expectedResult
    ratingChange = resultDiff * matchWeight
    #logging.debug("Rating Calc Input: pr:%d or:%d result:%.2f, gd:%d", playerRating, opponentRating, result, goalDifference)
    #logging.debug("Rating Calc Output: mw:%.2f er:%.2f rc:%.2f", matchWeight, expectedResult, ratingChange)
    return ratingChange

def UpdateRatingScore(game):
    winner = GetUserRecord( game.winner )
    loser = GetUserRecord( game.loser )

    if winner.rating == 0:
        winner.rating = ELO_DEFAULT_RATING
    if loser.rating == 0:
        loser.rating = ELO_DEFAULT_RATING

    #logging.debug("Rating Calc: winner:%s loser:%s", game.winner, game.loser)
    winnerRatingChange = CalcRatingChange(winner.rating, loser.rating, 1.0 if not game.tie else 0.5, game.winner_score - game.loser_score)
    loserRatingChange = CalcRatingChange(loser.rating, winner.rating, 0.0 if not game.tie else 0.5, game.loser_score - game.winner_score)

    winner.ratingChange = int(winnerRatingChange)
    winner.rating += winner.ratingChange
    winner.put()

    loser.ratingChange = int(loserRatingChange)
    loser.rating += loser.ratingChange
    loser.put()

# recalculate the rating score for all players from the beginning
def RecalcRatingScores():
    logging.debug("Recalculating all ratings scores")

    # get games oldest first
    gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).order('date')
    games = gameRecord_query.fetch(1000)

    # reset all users to default rating
    userRecord_query = UserRecord.all().filter("ladder =", ladder_name)
    userRecords = userRecord_query.fetch(1000)
    for userRecord in userRecords:
        userRecord.rating = 0
        userRecord.put()

    # update rating for each game
    for game in games:
        UpdateRatingScore( game );

# ------------------- Request Handlers ----------------------------------------------------------------------------------
class BasePage(webapp.RequestHandler):
    title = ''

    def write_page_header(self):
        self.response.headers['Content-Type'] = 'text/html'
        self.response.out.write('<html><head><title>%s</title>'
        '<link href="/stylesheets/main.css" rel="stylesheet" type="text/css"/>'
        '</head><body><div id="main">' % (
            self.title,))
        self.write_signin_links()

    def write_signin_links(self):
        if users.get_current_user():
          template_values = {
              'signed_in': True,
              'user_link': users.create_logout_url('/')}
        else:
          template_values = {
              'signed_in': False,
              'user_link': users.create_login_url('/')}
        path = os.path.join(os.path.dirname(__file__), 'templates')
        path = os.path.join(path, 'signin.html')
        self.response.out.write(template.render(path, template_values))

    def write_page_footer(self):
        self.response.out.write('</div></body></html>')

class MainPage(BasePage):
    title = 'Game Ladder'

    def get(self):
        template_values = {
            'ladders' : [ ladder_name ]
        }

        self.write_page_header()

        path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        self.response.out.write(template.render(path, template_values))

        self.write_page_footer()


class Ladder(BasePage):
    title = 'Game Ladder'

    def CreateDefaultUser(self):
        userRecord_query = UserRecord.all().filter("ladder =", ladder_name).filter("user =", users.get_current_user())
        if userRecord_query.count() > 0:
            return

        userRecord = UserRecord()
        userRecord.user = users.get_current_user()
        userRecord.ladder = ladder_name
        userRecord.put()

    def CreateLadder(self):
        userRecords = UserRecord.all().filter("ladder =", ladder_name).fetch(1000)

        ladderRecord = LadderRecord.all().filter("ladder =", ladder_name).get()
        if ladderRecord == None:
            ladderRecord = LadderRecord()
            ladderRecord.ladder = ladder_name
            ladderRecord.put()

        return ladderRecord

    def get(self):
        # create current user if he exists
        if users.get_current_user():
            self.CreateDefaultUser()

        # create a ladder if one doesn't exist
        self.CreateLadder()

        #RecalcRatingScores()

        # get all the users
        userRecords = UserRecord.all().filter("ladder =", ladder_name).order('-rating').fetch(1000)

        # Creating the data
        description = {"name": ("string", "Name"),
                     "rank": ("number", "Rank"),
                     "wins": ("number", "Wins"),
                     "losses": ("number", "Losses"),
                     "draws": ("number", "Draws"),
                     "gp": ("number", "Total"),
                     "gf": ("number", "Goals For"),
                     "ga": ("number", "Goals Against"),
                     "gd": ("number", "Goal Difference"),
                     "rating": ("number", "Rating"),
                     "+-": ("number", "+/-")}
        data = []

        for index, userRecord in enumerate(userRecords):
            user = userRecord.user
            stats = UserStats(user)
            name = user.email() if not userRecord.nickname else "%s (%s)" % (userRecord.nickname, user.email())
            data.append({"name": (user.email(), name),
                          "rank": index + 1,
                          "wins": stats.wins,
                          "losses": stats.losses,
                          "draws": stats.draws,
                          "gp": stats.wins + stats.losses + stats.draws,
                          "gf": stats.goalsfor,
                          "ga": stats.goalsagainst,
                          "gd": stats.goalsfor - stats.goalsagainst,
                          "rating" : userRecord.rating,
                          "+-": userRecord.ratingChange
                          })

        # Loading it into gviz_api.DataTable
        data_table = gviz_api.DataTable(description)
        data_table.LoadData(data)

        # Creating a JavaScript code string
        json = data_table.ToJSon(columns_order=("rank", "rating", "name", "+-", "wins", "draws", "losses", "gp", "gf", "ga", "gd"),
                                   order_by="rank")

        gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).order('-date')
        games = gameRecord_query.fetch(20)

        template_values = {
            'ladder_name' : ladder_name,
            'user': users.get_current_user(),
            'users': userRecords,
            'games': games,
            'json': json,
        }

        self.write_page_header()

        path = os.path.join(os.path.dirname(__file__), 'templates/ladder.html')
        self.response.out.write(template.render(path, template_values))

        self.write_page_footer()

class Resimulate(BasePage):
    def post(self):
        RecalcRatingScores()

        self.redirect('/%s/' % (ladder_name))


class Account(BasePage):
    title = 'My Account'

    def get(self):
        user = GetUserRecord( users.get_current_user() )
        if not user.nickname:
            user.nickname = user.user.nickname()

        template_values = {
            'ladder_name' : ladder_name,
            'user': user,
            'isAdmin': users.is_current_user_admin()
        }

        self.write_page_header()
        path = os.path.join(os.path.dirname(__file__), 'templates/account.html')
        self.response.out.write(template.render(path, template_values))

        self.write_page_footer()

    def post(self):
        user = GetUserRecord( users.get_current_user() )
        nickname = self.request.get('nickname')
        if nickname:
            user.nickname = nickname
            user.put()

        logging.debug("Nickname: %s", nickname)

        #self.response.out.write("nickname: " + user.nickname )

        self.redirect('/%s/' % (ladder_name))

class User(BasePage):
    title = 'User'

    def get(self):

        user = users.User( self.request.get('id') )
        userRecord = GetUserRecord( user )
        stats = UserStats(user)

        gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).filter('winner = ', user)
        games = gameRecord_query.fetch(1000)
        gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).filter('loser = ', user)
        games += gameRecord_query.fetch(1000)
        games.sort(lambda x,y: -cmp(x.date,y.date))


        # Creating the data
        description = {"type": "string", "number": "number"}
        data = ({"type": "Wins", "number": stats.wins}, {"type": "Losses", "number": stats.losses}, {"type": "Draws", "number": stats.draws})

        # Loading it into gviz_api.DataTable
        data_piechart = gviz_api.DataTable(description)
        data_piechart.LoadData(data)

        # Creating a JavaScript code string
        json = data_piechart.ToJSon(columns_order=("type", "number"))

        template_values = {
            'ladder_name' : ladder_name,
            'userRecord': userRecord,
            'games': games,
            'json': json,
        }

        self.write_page_header()
        path = os.path.join(os.path.dirname(__file__), 'templates/user.html')
        self.response.out.write(template.render(path, template_values))

        #self.response.out.write("userid: " + self.request.get('id') )

        self.write_page_footer()

class Report(BasePage):
    title = 'Report'

    def get(self):
        # get all the users
        userRecords = UserRecord.all().order('user').fetch(1000)
        # remove current user from opponent list
        opponents = [user for user in userRecords if user.user != users.get_current_user() ];

        template_values = {
            'ladder_name' : ladder_name,
            'user': users.get_current_user(),
            'opponents': opponents
        }

        self.write_page_header()
        path = os.path.join(os.path.dirname(__file__), 'templates/report.html')
        self.response.out.write(template.render(path, template_values))
        self.write_page_footer()

    def post(self):
        player_score = int_safe( self.request.get('player_score') )
        opponent_score = int_safe( self.request.get('opponent_score') )

        game = GameRecord()
        game.ladder = ladder_name
        game.winner_score = max(player_score, opponent_score)
        game.loser_score = min(player_score, opponent_score)
        if self.request.get('win') == 'win':
            game.winner = users.get_current_user()
            game.loser = users.User( self.request.get('opponent') )
            game.winner_team = self.request.get('player_team')
            game.loser_team = self.request.get('opponent_team')
        else:
            game.winner = users.User( self.request.get('opponent') )
            game.loser = users.get_current_user()
            game.winner_team = self.request.get('opponent_team')
            game.loser_team = self.request.get('player_teamn')
        game.tie = self.request.get('win') == 'draw'

        #self.response.out.write( "winner_score: " + str(game.winner) )

        # hmm, bad data...
        if game.winner == game.loser:
            self.redirect('/%s/' % (ladder_name))

        commentText = self.request.get('comment');
        if commentText:
            comment = CommentRecord()
            comment.text = commentText
            comment.user = users.get_current_user()
            comment.put()

            game.comments.append( comment.key() )


        game.put()

        # Update elo ratings
        UpdateRatingScore( game );

        self.redirect('/%s/' % (ladder_name))



application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/%s' % (ladder_name), Ladder),
                                      ('/%s/' % (ladder_name), Ladder),
                                      ('/%s/resimulate' % (ladder_name), Resimulate),
                                      ('/%s/report' % (ladder_name), Report),
                                      ('/%s/account' % (ladder_name), Account),
                                      ('/%s/user' % (ladder_name), User)],
                                     debug=True)

def main():
    logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
  main()
