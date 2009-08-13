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

win_ladder_move_percent = 0.5
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
    text = db.StringProperty()

class GameRecord(db.Model):
    ladder = db.StringProperty()
    winner = db.UserProperty()
    loser = db.UserProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    winner_score = db.IntegerProperty()
    loser_score = db.IntegerProperty()
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
    ranks = db.ListProperty(users.User)
    date = db.DateTimeProperty(auto_now_add=True)

    def UpdateLadder(self, gameRecord):
        winnerIndex = self.ranks.index( gameRecord.winner )
        loserIndex = self.ranks.index( gameRecord.loser )
        # no change if winner was already better
        if winnerIndex < loserIndex:
            return

        newIndex = int(math.floor( (winnerIndex - loserIndex) * win_ladder_move_percent )) + loserIndex
        del self.ranks[ winnerIndex ]
        self.ranks.insert(newIndex, gameRecord.winner )
        self.put()

# ------------------- Helper classes ----------------------------------------------------------------------------------
# get player wins/losses by reading game records
class UserStats:
    def __init__(self, user):
        winQuery = GameRecord.all().filter("ladder =", ladder_name).filter("winner =", user)
        loseQuery = GameRecord.all().filter("ladder =", ladder_name).filter("loser =", user)
        self.wins = winQuery.count()
        self.losses = loseQuery.count()
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
    logging.debug("Rating Calc Input: pr:%d or:%d result:%.2f, gd:%d", playerRating, opponentRating, result, goalDifference)
    logging.debug("Rating Calc Output: mw:%.2f er:%.2f rc:%.2f", matchWeight, expectedResult, ratingChange)
    return ratingChange

# recalculate the rating score for all players from the beginning
def RecalcRatingScores():
    # get games oldest first
    gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).order('date')
    games = gameRecord_query.fetch(1000)

    # reset all users to default rating
    userRecord_query = UserRecord.all().filter("ladder =", ladder_name)
    userRecords = userRecord_query.fetch(1000)
    for userRecord in userRecords:
        userRecord.rating = ELO_DEFAULT_RATING
        userRecord.put()

    # update rating for each game
    for game in games:
        winner = GetUserRecord( game.winner );
        loser = GetUserRecord( game.loser );

        logging.debug("Rating Calc: winner:%s loser:%s", game.winner, game.loser)
        winnerRatingChange = CalcRatingChange(winner.rating, loser.rating, 1.0, game.winner_score - game.loser_score)
        loserRatingChange = CalcRatingChange(loser.rating, winner.rating, 0.0, game.loser_score - game.winner_score)

        winner.ratingChange = int(winnerRatingChange)
        winner.rating += winner.ratingChange
        winner.put()

        loser.ratingChange = int(loserRatingChange)
        loser.rating += loser.ratingChange
        loser.put()

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

    def RefreshLadderWithAllUsers(self):
        userRecords = UserRecord.all().filter("ladder =", ladder_name).fetch(1000)

        ladderRecord = LadderRecord.all().filter("ladder =", ladder_name).get()
        if ladderRecord == None:
            ladderRecord = LadderRecord()
            ladderRecord.ladder = ladder_name

        for user in userRecords:
            if user.user not in ladderRecord.ranks:
                ladderRecord.ranks.append( user.user )

        ladderRecord.put()

    def get(self):
        # create current user if he exists
        if users.get_current_user():
            self.CreateDefaultUser()

        # update ladder with all users and get it
        self.RefreshLadderWithAllUsers()
        ladderRecord = LadderRecord.all().filter("ladder =", ladder_name).get()

        #RecalcRatingScores()

        # get all the users
        userRecords = UserRecord.all().filter("ladder =", ladder_name).order('-rating').fetch(1000)

        # Creating the data
        description = {"name": ("string", "Name"),
                     "rank": ("number", "Rank"),
                     "wins": ("number", "Wins"),
                     "losses": ("number", "Losses"),
                     "gp": ("number", "Total"),
                     "gf": ("number", "Goals For"),
                     "ga": ("number", "Goals Against"),
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
                          "gp": stats.wins + stats.losses,
                          "gf": stats.goalsfor,
                          "ga": stats.goalsagainst,
                          "rating" : userRecord.rating,
                          "+-": userRecord.ratingChange
                          })

        # Loading it into gviz_api.DataTable
        data_table = gviz_api.DataTable(description)
        data_table.LoadData(data)

        # Creating a JavaScript code string
        json = data_table.ToJSon(columns_order=("rank", "rating", "name", "+-", "wins", "losses", "gp", "gf", "ga"),
                                   order_by="rank")

        gameRecord_query = GameRecord.all().filter("ladder =", ladder_name).order('-date')
        games = gameRecord_query.fetch(10)

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

class Account(BasePage):
    title = 'My Account'

    def get(self):
        user = GetUserRecord( users.get_current_user() )
        if not user.nickname:
            user.nickname = user.user.nickname()

        template_values = {
            'ladder_name' : ladder_name,
            'user': user
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
        data = ({"type": "Wins", "number": stats.wins}, {"type": "Losses", "number": stats.losses})

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
        userRecords = UserRecord.all().fetch(1000)
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
        else:
            game.winner = users.User( self.request.get('opponent') )
            game.loser = users.get_current_user()

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

        # update ladder with game record
        ladder = LadderRecord.all().filter("ladder =", ladder_name).get()
        ladder.UpdateLadder( game )

        # Update elo ratings
        # TODO: only recalc newly added game
        RecalcRatingScores()

        self.redirect('/%s/' % (ladder_name))



application = webapp.WSGIApplication(
                                     [('/', MainPage),
                                      ('/%s' % (ladder_name), Ladder),
                                      ('/%s/' % (ladder_name), Ladder),
                                      ('/%s/report' % (ladder_name), Report),
                                      ('/%s/account' % (ladder_name), Account),
                                      ('/%s/user' % (ladder_name), User)],
                                     debug=True)

def main():
    #logging.getLogger().setLevel(logging.DEBUG)
    run_wsgi_app(application)

if __name__ == "__main__":
  main()
