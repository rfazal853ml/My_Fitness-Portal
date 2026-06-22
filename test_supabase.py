# test_supabase.py  (run once, then delete)
from services.supabase_client import get_supabase

db = get_supabase()

# Should return your 3 roles
roles = db.table("roles").select("name, description").execute()
print("Roles:", roles.data)

# Should return your 19 permissions
perms = db.table("permissions").select("module, action", count="exact").execute()
print("Permission count:", perms.count)

# Should return gym_name = 'My Gym'
setting = db.table("settings").select("value").eq("key", "gym_name").single().execute()
print("Gym name:", setting.data["value"])