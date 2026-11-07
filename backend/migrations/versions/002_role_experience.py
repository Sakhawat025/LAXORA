"""Profile detail, single-use admin invitations and direct messaging."""
from alembic import op
import sqlalchemy as sa
revision='002'
down_revision='001'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('users',sa.Column('city',sa.String(120),nullable=False,server_default=''))
    op.add_column('users',sa.Column('address',sa.String(500),nullable=False,server_default=''))
    op.add_column('users',sa.Column('bio',sa.Text(),nullable=False,server_default=''))
    op.create_table('admin_invites',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('email',sa.String(254),nullable=False),sa.Column('token_hash',sa.String(64),nullable=False,unique=True),sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),sa.Column('used',sa.Boolean(),nullable=False),sa.Column('created_by',sa.Integer(),sa.ForeignKey('users.id'),nullable=True))
    op.create_index('ix_admin_invites_email','admin_invites',['email'])
    op.create_table('conversations',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('client_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('lawyer_user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_conversations_client_id','conversations',['client_id'])
    op.create_index('ix_conversations_lawyer_user_id','conversations',['lawyer_user_id'])
    op.create_index('unique_direct_pair','conversations',['client_id','lawyer_user_id'],unique=True)
    op.create_table('direct_messages',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('conversation_id',sa.Integer(),sa.ForeignKey('conversations.id'),nullable=False),sa.Column('sender_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('body',sa.Text(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('read_at',sa.DateTime(timezone=True),nullable=True))
    op.create_index('ix_direct_messages_conversation_id','direct_messages',['conversation_id'])

def downgrade():
    op.drop_table('direct_messages');op.drop_table('conversations');op.drop_table('admin_invites')
    for name in ['bio','address','city']:op.drop_column('users',name)
