import os

import discord
from discord.ext import commands
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
client = MongoClient(os.getenv('MONGODB_URL'))
db = client['jbucks']

bot = commands.Bot('j!', commands.DefaultHelpCommand(no_category="JBucks"))

import user

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.BadArgument):
        await ctx.send('Bad arguments')
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('You do not have permission to run this command')
    raise error

@bot.command(name='daily', help='print your daily JBuck')
async def daily(ctx):
    juser = user.JUser(ctx.author.id)
    if juser.daily_available:
        juser.daily()
        await ctx.send('You have gained one (1) Jbuck. You now have {} Jbucks'.format(juser.jbucks))
    else:
        await ctx.send('You are attempting to gain more than ur alloted Jbucks'.format(juser.jbucks))
    juser.save()

@bot.command(name='pay', help='pay <amount> <@user> <reason?>')
async def pay(ctx, amount: float, target: discord.Member, *reasons):
    juser = user.JUser(ctx.author.id)
    target_user = user.JUser(target.id)
    reason = ' '.join(reasons)

    if amount <= 0:
        await ctx.send('You can only send a positive amount of JBucks')
        return

    if juser.jbucks < amount:
        await ctx.send('You are too poor for this request (You have {} Jbucks)'.format(juser.jbucks))
        return

    juser.add_jbucks(round(-1. * amount, 2))
    target_user.add_jbucks(amount)
    db.transactions.insert_one({
        'ts': datetime.now(),
        'from': juser.user_id,
        'to': target_user.user_id,
        'amount': amount,
        'reason': reason,
    })
    juser.save()
    target_user.save()
    await ctx.send('You have paid {} Jbucks to {}#{}. You now have {} Jbucks and they have {}.'
                   .format(amount, target.name, target.discriminator, juser.jbucks, target_user.jbucks))

@bot.command(name='viewjobs', brief='viewjobs <type?>',
    help='"posted" to see only your jobs; "accepted" to see accepted by you; "all" to see all, including accepted')
async def viewjobs(ctx, mine=None):
    fil = {}
    if mine == 'posted':
        fil = {'accepted': 0, 'employer': ctx.author.id}
    elif mine == 'accepted':
        juser = user.JUser(ctx.author.id)
        fil = {'accepted': juser.id}
    elif mine == 'all':
        fil = {}
    else:
        fil = {'accepted': 0}
    embed = discord.Embed(title='Current Jobs')
    if db.jobs.count_documents(fil) == 0:
        await ctx.send("No jobs found")
        return
    for job in db.jobs.find(fil):
        embed.add_field(name=job.get('name', "No Name"), value=await get_job_output(job))
    await ctx.send(embed=embed)

async def get_job_output(job):
    employer = await bot.fetch_user(job.get('employer'))
    if not employer:
        return "Employer no longer available"

    income_str = ""
    if job.get('income') > 0:
        income_str = 'Income: {}'.format('income', 0)
    else:
        income_str = 'Cost: {}'.format(-1 * job.get('income', 0))

    accepted_str = ""
    if job.get('accepted'):
        accepted_by =  await bot.fetch_user(job.get('accepted'))
        accepted_str = "\nAccepted by: {}#{}".format(accepted_by.name, accepted_by.discriminator)
    return r"""
        ID: {}
        {}
        Repeats: {}
        Employer: {}
        Description: {}{}
    """.format(job.get('_id'),
               income_str,
               job.get('repeats', 'never'),
               '{}#{}'.format(employer.name, employer.discriminator),
               job.get('description', ''),
               accepted_str,
    )

@bot.command(name='postservice', brief='postservice <cost> <never|daily> <name>:<description>',
    help='If "never" is set, there is a one-time transfer when the job is accepted.')
async def postservice(ctx, income: float, repeats, *args):
    await postjob(ctx, income, repeats, *args)

@bot.command(name='postjob', brief='postjob <income> <never|daily> <name>:<description>',
    help='If "never" is set, there is a one-time transfer when the job is accepted.')
async def postjob(ctx, income: float, repeats, *args):
    if repeats not in ['never', 'daily']:
        await ctx.send("Please specify if the job pays once or daily")
        return
    [name, description] = (' '.join(args)).split(':')
    new_job = {
        'income': income,
        'repeats': repeats,
        'name': name,
        'description': description,
        'employer': ctx.author.id,
        'accepted': 0,   
    }
    db.jobs.insert_one(new_job)
    embed = discord.Embed()
    embed.add_field(name=name, value=await get_job_output(new_job))
    await ctx.send('Successfully Added Job', embed=embed)

@bot.command(name='deletejob', help='deletejob <job_id>')
async def deletejob(ctx, job_id):
    job = db.jobs.find_one({'_id': ObjectId(job_id)})
    if not job:
        await ctx.send("Could not find job")
        return

    if job.get('employer') != ctx.author.id:
        await ctx.send("This is not your job")
        return

    if db.jobs.delete_one({'_id': ObjectId(job_id)}).deleted_count:
        await ctx.send("Successfully Deleted Job {}".format(job_id))

@bot.command(name='acceptjob', help='acceptjob <job_id>')
async def acceptjob(ctx, job_id):
    job = db.jobs.find_one({'_id': ObjectId(job_id)})
    if not job:
        await ctx.send("Could not find job")
        return

    if job.get('accepted'):
        await ctx.send("Job is already taken")
        return

    juser = user.JUser(ctx.author.id)
    juser.save()

    employer = await bot.fetch_user(job.get('employer'))
    embed = discord.Embed()
    embed.add_field(name=job.get('name'), value=await get_job_output(job))
    await ctx.send('Hey {}, {} has accepted your job:'.format(employer.mention if employer else job.get('employer'), ctx.author.mention), embed=embed)

    if job.get('repeats') == 'never':
        await transfer(ctx, user.JUser(job.get('employer')), employer.mention, juser, ctx.author.mention, job.get('income'))
    else:
        db.jobs.update_one({'_id': ObjectId(job_id)}, {'$set': {'accepted': ctx.author.id}})

@bot.command(name='quitjob', help='quitjob <job_id>')
async def quitjob(ctx, job_id):
    juser = user.JUser(ctx.author.id)
    job = db.jobs.find_one({'_id': ObjectId(job_id)})

    if not job:
        await ctx.send("Could not find job")
        return

    if job.get('accepted') != ctx.author.id:
        await ctx.send("This is not your job")
        return

    juser.save()
    db.jobs.update_one({'_id': ObjectId(job_id)}, { '$set': {'accepted': 0}})

    embed = discord.Embed()
    job['accepted'] = 0
    embed.add_field(name=job.get('name'), value=await get_job_output(job))
    await ctx.send('You have quit your job:', embed=embed)

async def transfer(ctx, source, source_mention, to, to_mention, amount):
    if amount > 0:
        source.jbucks -= amount
        to.jbucks += round(.9 * amount, 2)
        add_prize_pool(round(.1 * amount, 2))
        await ctx.send('{} has transferred {} JBucks to {}.\n{} of that amount has been taxed and added to the Jelly Prize Pool (JPP)'.format(
            source_mention,
            amount,
            to_mention,
            round(.1 * amount, 2),
        ))
    else:
        amount = -1 * amount
        source.jbucks += round(.9 * amount, 2)
        to.jbucks -= amount
        add_prize_pool(round(.1 * amount, 2))
        await ctx.send('{} has transferred {} JBucks to {}.\n{} of that amount has been taxed and added to the Jelly Prize Pool (JPP)'.format(
            to_mention,
            amount,
            source_mention,
            round(.1 * amount, 2),
        ))

    source.save()
    to.save()

@bot.command(name='bal', brief='bal <user?>',
    help='check your jbucks balance, or that of a mentioned user')
async def bal(ctx, usr : discord.Member = None):
    if usr:
        juser = user.JUser(usr.id)
        await ctx.send('{}#{}\'s current balance is {} Jbucks'.format(usr.name, usr.discriminator, juser.jbucks))
    else:
        juser = user.JUser(ctx.author.id)
        await ctx.send('Your current balance is {} Jbucks'.format(juser.jbucks))

@bot.command(name='prizepool', help='check prizepool')
async def prizepool(ctx):
    await ctx.send('The current prize pool is {} Jbucks'.format(db.globals.find_one({'key': 'prize_pool'}).get('value', 0)))

@bot.command(name='gift', brief='gift <user> <amt> (admin only)', help='gifts Jbucks to target user (out of thin air) (admin only')
@commands.has_permissions(administrator=True)
async def gift(ctx, usr: discord.Member, amt: float):
    juser = user.JUser(usr.id)
    juser.jbucks += amt
    juser.save()
    await ctx.send('{} Jbucks have been generously gifted to {}#{} by the Jelly gods'.format(amt, usr.name, usr.discriminator))

@bot.command(name='award', brief='award <user> (admin only)', help='awards all JBucks in prize pool to target user (admin only)')
@commands.has_permissions(administrator=True)
async def award(ctx, usr: discord.Member):
    amt = db.globals.find_one({'key': 'prize_pool'}).get('value', 0)
    if amt > 0:
        juser = user.JUser(usr.id)
        juser.jbucks += amt
        juser.save()

        db.globals.update_one({'key': 'prize_pool'}, { '$set': {'value': 0}})

        await ctx.send('{} Jbucks have been awarded to {}#{} from the prize pool, which is now empty'.format(amt, usr.name, usr.discriminator))

@bot.command(name='victory', brief='we won colo, so everyon get jbuck (admin only)')
@commands.has_permissions(administrator=True)
async def victory(ctx):
    db.user.update_many({}, { '$inc': {'jbucks': 1}})
    await ctx.send('We won colo! <:mikudab:728469356605866016> Everyone gets one (1) JBuck')

@bot.command(name='leaderboard', help='check jbucks leaderboard')
async def leaderboard(ctx):
    embed = discord.Embed(title="The Official Jelly JBucks Leaderboard")
    for entry in db.user.find({}).sort('jbucks', -1):
        usr = await bot.fetch_user(entry.get('user_id'))
        embed.add_field(name='{}#{}'.format(usr.name, usr.discriminator), value=entry.get('jbucks'), inline=False)
    await ctx.send(embed=embed)

def add_prize_pool(amount):
    db.globals.update_one({'key': 'prize_pool'}, { '$inc': {'value': amount}})

if __name__ == '__main__':
    bot.run(TOKEN)