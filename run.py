# -*- coding: utf-8 -*-

import sys, os
import requests
import inspect
import json
import getpass
import datetime
import re


tasks = []

class TaskFailure(Exception):
    pass

#tasks cannot have kwargs
class Task(object):
    def __init__(self, f, name, help_text, args):
        self.f = f
        self.help_text = help_text
        self.args = args
        self.name = name
    def __call__(self, *args):
        if len(args) != len(self.args):
            l = len(self.args)
            raise TaskFailure("{} expects {} argument{}: {}".format(
                self.name, l, 's' if l!=1 else '',' '.join(self.args)))
        self.f(*args)
        print "Success!!"

def task(help_text=''):
    def decorator(f):
        task_name = f.__name__
        args = inspect.getargspec(f).args
        t = Task(f, task_name, help_text, args)
        tasks.append(t)
        return t
    return decorator

def usage():
    print
    print "Usage:"
    print
    print "    >> python run.py task_name arg1 arg2 ..."
    print
    print
    print "Available Tasks:"
    for t in tasks:
        print
        print "    >> python run.py {} {}".format(t.name,' '.join(t.args))
        print
        print "        {}".format(t.help_text.strip().replace('\n','\n        '))
    print

def run():
    try:
        task_name = sys.argv[1]
    except:
        task_name = None
    for t in tasks:
        if t.name == task_name:
            try:
                t(*sys.argv[2:])
            except TaskFailure as e:
                print
                print e.message
                print
            return
    usage()

##########################################
#
#   Task definitions
#
##########################################

class GithubWrapper(object):
    def __init__(self, token):
        self.token = token
    @staticmethod
    def url(s):
        return "https://api.github.com/{}".format(s.strip('/'))
    def do(self,f, path, **kwargs):
        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        kwargs['headers']['Authorization'] = "token {}".format(self.token)
        url = self.url(path)
        return getattr(requests,f)(url,**kwargs)
    def __getattr__(self,name):
        if name in ['get','post','delete','put','head','options']:
            def tmp(path,*args,**kwargs):
                return self.do(name,path,**kwargs)
            return tmp
    def has_admin_access(self):
        path = '/orgs/6170'
        r = self.post(path,data=json.dumps({}))
        return r.status_code == 200

    @staticmethod
    def load():
        token = ''
        try:
            with open("token.txt") as f:
                token = f.read().strip()
        except:
            pass
        g = GithubWrapper(token)
        if not g.has_admin_access():
            raise TaskFailure("Github api token is either missing or invalid. "\
                    "Please run the get_auth_token task to create a new one")
        return g

    def save(self):
        with open("token.txt","w") as f:
            f.write(self.token)
    
    def get_or_create_team(self,team_name):
        all_teams = self.get("orgs/6170/teams").json
        all_teams_dict = dict((x['name'],x['id']) for x in all_teams)
        if team_name not in all_teams_dict:
            data = {
                    "name":team_name,
                    "permission":"admin",
                    }
            print "Creating team with name {}".format(team_name)
            r = self.post("/orgs/6170/teams", data=json.dumps(data))
            if r.status_code != 201:
                raise TaskFailure("Failed to create team")
        else:
            team_id = all_teams_dict[team_name]
            print "Fetching team {}".format(team_id)
            r = self.get("/teams/{}".format(team_id))
            if r.status_code != 200:
                raise TaskFailure("Failed to fetch team")
        return r.json
    
    def add_user(self, athena, github):
        team_name = "{}_{}".format(athena,github)
        team = self.get_or_create_team(team_name)
        print team
        print "Addin user {} to team {}".format(github, team['id'])
        r = self.put("/teams/{}/members/{}/".format(team['id'], github),headers={"Content-Length":'0'})
        if r.status_code != 204:
            raise TaskFailure("Failed to add user to team")
        return team

    def create_repo(self, repo_name, team_id):
        data = {
                "name":repo_name,
                "private":True,
                "team_id":team_id,
                }
        r = self.post('/orgs/6170/repos',data=json.dumps(data))
        if r.status_code != 201:
            raise TaskFailure("Failed to create repo: {}".format(r.content))
        return r.json

    def iterate_repos(self):
        #unless I see otherwise, I assume that pagination is broken on this resource
        """
        counter = 0
        while True:
            r = self.get("/orgs/6170/repos",params={'page':counter, 'per_page':1})
            repos = r.json
            print r.url
            print r.headers
            if len(repos) == 0:
                return
            for r in repos:
                yield r
            counter += 1
            """
        r = self.get("/orgs/6170/repos")
        return r.json


@task("""
Gets a Github API token and stores it in token.txt
The token will be used for all subsequent requests
to the Github API.
""")
def get_auth_token():
    print "Enter your Github credentials"
    username = raw_input("Username: ")
    password = getpass.getpass("Password: ")
    url = GithubWrapper.url('/authorizations')
    data = {
            "scopes":['gist','delete_repo','repo:status',
                'repo','public_repo','user'],
            "note":"6.170 student repo management script",
            }
    r = requests.post(url,data=json.dumps(data),auth=(username,password))
    if r.status_code != 201:
        raise TaskFailure("Your github credentials were invalid")
    g = GithubWrapper(r.json['token'])
    if not g.has_admin_access():
        raise TaskFailure("Your github account does not have admin access to "\
                "the 6.170 organization. Please make yourself an owner.")
    g.save()


@task("""
Creates a repo with the name "username_project"

Reads from stdin. Each line should have two tokens
separated by whitespace. The first token is the
student's athena name. The second is the github id
(username) beloning to the student.

The repository will be initialized with the
a clone of git@github.com:6170/project_name.git
""")
def make_repos(project_name):
    g = GithubWrapper.load()
    try:
        cwd = os.getcwd()
        os.chdir("/tmp")
        os.system("rm -rf {}".format(project_name))
        handout_code_repo = "git@github.com:6170/{}.git".format(project_name)
        clone_successful = os.system("git clone {}".format(handout_code_repo)) == 0
        if not clone_successful:
            raise TaskFailed("Could not clone {}. Make sure that the repository exists, and that"\
                    "your github private key is installed on this system".format(project_name))
        os.chdir(project_name)
        for line in sys.stdin:
            if not line:
                print "Encountered empty line. Exiting"
                return
            print "Processing: {}".format(line)
            try:
                athena, github = line.split()
            except:
                print 'Line: "{}" must be of the form "athena_name github_name". Skipping'.format(line)
                continue
            try:
                print 'Adding user'
                team = g.add_user(athena,github)
            except Exception as e:
                print "Failed to add user: {}".format(e)
                continue
            try:
                repo_name = "{}_{}".format(athena,project_name)
                print 'Creating repo: {}'.format(repo_name)
                repo = g.create_repo(repo_name,team['id'])
            except Exception as e:
                print "Failed to create repo: {}".format(e)
                continue
            print "Pushing the handout code"
            push_successful = os.system("git push {} master".format(repo['ssh_url'])) == 0
            if not push_successful:
                print "Failed to initialize repository with the handout code"
    finally:
        os.system("rm -rf {}".format(project_name))
        os.chdir(cwd)

@task("""
Clones all repos beloning to the supplied project_name
and stores them in a new subfolder of the ./cloned_repos
directory.
""")
def clone_repos(project_name):
    g = GithubWrapper.load()
    dirname = os.path.join("cloned_repos","{} {}".format(
        project_name, str(datetime.datetime.now())))
    os.makedirs(dirname)
    try:
        cwd = os.getcwd()
        os.chdir(dirname)
        for r in g.iterate_repos():
            if re.match(r'.+{}$'.format(project_name),r['name']):
                print "Cloning {}".format(r['ssh_url'])
                clone_success = os.system("git clone {}".format(r['ssh_url'])) == 0
                if not clone_success:
                    print "Clone Failed"
    finally:
        os.chdir(cwd)




if __name__ == '__main__':
    run()
