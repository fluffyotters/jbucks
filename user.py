from app import db
from datetime import datetime
from doc import Doc

class JUser(Doc):
    collection = db.user
    def __init__(self, user_id):
        self.user_id = user_id
        self.jbucks = 0
        self.daily_value = 1
        self.daily_available = True
        self.load(db.user.find_one({'user_id': user_id}))

    def primary_fil(self):
        return {'user_id': self.user_id}

    def daily(self):
        self.daily_available = False
        self.add_jbucks(self.daily_value)
        msg = 'You have gained {} Jbucks. You now have {} Jbucks'.format(self.daily_value, self.jbucks)
        if self.daily_value < 5:
            self.daily_value += 1
        return msg

    def add_jbucks(self, amt):
        self.jbucks += amt
