from copy import deepcopy
from datetime import datetime, date, timedelta
from genshi.builder import tag
from genshi.filters.transform import Transformer

from trac.config import Option, BoolOption, ListOption
from trac.core import Component, Interface, implements
from trac.ticket.api import ITicketChangeListener
from trac.ticket.model import Type
from trac.util.compat import set
from trac.util.datefmt import to_datetime, to_timestamp, localtz
from trac.util.translation import _

from itteco.init import IttecoEvnSetup
from itteco.ticket.model import StructuredMilestone

class IBurndownInfoProvider(Interface):
    def metrics(milestone):
        """ Returns mertics for building charts."""    

class AbstractBurndownInfoProvider(Component):
    implements ( IBurndownInfoProvider)
    
    """ Extension option for snapshot strategy that is to be used building burndown"""
    abstract = True
    
    fill_idle_days = BoolOption('itteco-whiteboard-config', 'show_idle_days_on_burndown', 
        False,
        doc="Switch on/off display of horisontal line on idle days within a burndown chart.")
        
    initial_plan_element = ListOption('itteco-whiteboard-tickets-config', 'initial_plan_element', 
        ['task'],
        doc="Job progress for a burndown chart would be calculated in the given type of ticket.")
    
    count_burndown_on = Option('itteco-whiteboard-config', 'count_burndown_on', "complexity",
        doc="""Job progress for a burndown chart would be calculated on this type of field. 
            Possible values are: name of a custom field or 'quantity'.""")

    def _milestone_scope(self, milestone):
        """ Returns numeric representation of the scope for given milestone """
        
        mils = [milestone.name]
        tkt_types = None
        if self.count_burndown_on=='quantity':        
            mils += [m.name for m in milestone.kids]
            tkt_types = self._work_types()
        else:
            all_types = Type.select(self.env)
            tkt_types = [type.name for type in all_types 
                if type.name in IttecoEvnSetup(self.env).scope_element]
           
        return self._calculate_scope(mils, tkt_types)

    def _calculate_scope(self, mil_names, tkt_type=None, db=None):
        """ Calculated scope based on selected miletones and ticket types."""
        
        db= db or self.env.get_db_cnx()
        cursor = db.cursor()
        
        sql = None
        params = list(mil_names)
        if self.count_burndown_on =='quantity':
            sql = "SELECT count(t.id) FROM ticket t " + \
                "WHERE t.milestone IN (%s)" % ("%s,"*len(mil_names))[:-1]
        else:
            sql = "SELECT sum("+db.cast(db.concat('0','tc.value'),'int')+")"+ \
                " FROM ticket t, ticket_custom tc"+ \
                " WHERE t.milestone IN (%s)" % ("%s,"*len(mil_names))[:-1]+\
                " AND t.id=tc.ticket AND tc.name=%s" 
            params +=[self.count_burndown_on]
        if tkt_type:
            if isinstance(tkt_type, basestring):
                sql +=" AND t.type=%s"
                params +=[tkt_type]
            else:
                sql +=" AND t.type IN (%s)" % ("%s,"*len(tkt_type))[:-1]
                params += list(tkt_type)
        
        cursor.execute(sql, params)
        sum, = cursor.fetchone()
        return sum

    def _burnup_info(self, milestone):
        mils = [milestone.name]+[m.name for m in milestone.kids]
        tkt_types = None
        if self.count_burndown_on!='quantity':        
            all_types = Type.select(self.env)
            tkt_types = [type.name for type in all_types 
                if type.name not in IttecoEvnSetup(self.env).scope_element]
        else:
            #the only way to count progress on the tickets quantity is to have 
            # the same set of tickets for scope and for progress calculations
            tkt_types = self._work_types()
        return self._get_job_done(mils, tkt_types)
    
    def _work_types(self):
        """ Returns ticket types that are taken into consideration 
        while counting milestone progress """        
        return list(set(IttecoEvnSetup(self.env).work_element) - \
            set(self.initial_plan_element))
        
    def metrics(self, milestone):
        mil = StructuredMilestone(self.env, milestone)
        if not mil.is_started:
            return None

        scope = self._milestone_scope(mil)
        
        scope_types = IttecoEvnSetup(self.env).scope_element
        types = self._work_types()
        one_day_delta = timedelta(1)
        
        metrics = [{'datetime': mil.started, 'burndown': scope, 'burnup': [0]*len(types)}]
        def clone_item(item, new_time):
            item = deepcopy(item)
            item['datetime']= new_time
            metrics.append(item)
            return item
            
        for ts, ttype, sum in self._burnup_info(mil):
            last = metrics[-1]
            if ts!=last['datetime']:
                if self.fill_idle_days:
                    time_delta = ts - last['datetime']
                    if time_delta.days>1:
                        last = clone_item(last, ts-one_day_delta)
                last = clone_item(last, ts)

            if ttype in self.initial_plan_element:
                #this ticket type should influence burndown
                last['burndown'] -= sum
            elif ttype not in scope_types:
                #burnup by ticket type turned around axis X, in order to look like burndown
                idx = types.index(ttype)
                last['burnup'][idx] += sum                
        
        calculated_end_date = None
        if len(metrics)>1:# do we have any progress?
            start = metrics[0]
            end = metrics[-1]
            if start['burndown']!=end['burndown']:
                # do we have any progress to perform approximations?
                start_ts = to_timestamp(start['datetime'])
                end_ts = to_timestamp(end['datetime'])
                calc_ts = start_ts+ \
                    start['burndown']*(end_ts - start_ts)/ \
                        (start['burndown']-end['burndown'])
                end['approximation']=end['burndown']                
                calculated_end_date = to_datetime(calc_ts)
        
        if mil.due:#if milestone is fully planned, add line of ideal progress
            if mil.due>metrics[-1]['datetime']:
                metrics.append({'datetime': mil.due})
            metrics[0]['ideal']= scope
            metrics[-1]['ideal']= 0
            
        if calculated_end_date:            
            if calculated_end_date > metrics[-1]['datetime']:
                metrics.append({'datetime': calculated_end_date, 'approximation': 0})
            else:
                #let's find a correct place on timeline for calculated end date
                for i in xrange(0, len(metrics)):
                    metric = metrics[i]
                    if metric['datetime']>=calculated_end_date:
                        if metric['datetime']>calculated_end_date:
                            metric = {'datetime':calculated_end_date}
                            metrics.insert(i, metric)
                        metric['approximation'] = 0
                        break
        
        return metrics, types

        
class BuildBurndownInfoProvider(AbstractBurndownInfoProvider):
    """ The progress of the sprint is calculated only appon the completed builds
        within the sprint."""
        
    def _get_job_done(self, mil_names, tkt_type=None, db=None):
        db= db or self.env.get_db_cnx()
        cursor = db.cursor()
        
        base_sql = None
        params = list(mil_names)
        if self.count_burndown_on =='quantity':
            base_sql = "SELECT m.completed, t.type, count(t.id) FROM ticket t, milestone m"+ \
                " WHERE m.name IN (%s)" % ("%s,"*len(mil_names))[:-1] + \
                " AND m.completed IS NOT NULL AND m.completed>0"+ \
                " AND m.name=t.milestone" 
        else:
            base_sql = "SELECT m.completed, t.type, sum("+db.cast(db.concat('0','tc.value'),'int')+")"+ \
                " FROM ticket t, ticket_custom tc, milestone m "+ \
                " WHERE m.name IN (%s)" % ("%s,"*len(mil_names))[:-1] + \
                " AND m.completed IS NOT NULL AND m.completed>0"+ \
                " AND m.name=t.milestone AND t.id=tc.ticket AND tc.name=%s" 
            params +=[self.count_burndown_on]
        if tkt_type:#we nave ticket type limitations            
            if isinstance(tkt_type, basestring):
                base_sql +=" AND t.type=%s"
                params +=[tkt_type]
            else:
                base_sql +=" AND t.type IN (%s)" % ("%s,"*len(tkt_type))[:-1]
                params += list(tkt_type)
        
        cursor.execute(base_sql+" GROUP BY t.type, m.completed ORDER BY 1", params)
        data = [(to_datetime(dt), ttype, sum) for dt, ttype, sum in cursor]
        return data

class DateBurndownInfoProvider(AbstractBurndownInfoProvider):
    """ The Sprint progress is calculated as soon as ticket is closed."""
    
    def _get_job_done(self, mil_names, tkt_type=None, db=None):
        started_at = to_timestamp(datetime(tzinfo=localtz, \
            *(StructuredMilestone(self.env, mil_names[0]).started.timetuple()[:3])))
        db= db or self.env.get_db_cnx()
        cursor = db.cursor()
        
        base_sql = None
        params = list(mil_names)
        group_by = " GROUP BY t.id, t.type"
        final_statuses = IttecoEvnSetup(self.env).final_statuses
        status_params = ("%s,"*len(final_statuses))[:-1]
        params = final_statuses+ final_statuses + params
        if self.count_burndown_on =='quantity':
            base_sql = """SELECT MAX(c.time), t.id, t.type, 1
                FROM ticket t 
                    LEFT JOIN milestone m ON m.name=t.milestone 
                    LEFT OUTER JOIN ticket_change c ON t.id=c.ticket 
                        AND c.field='status' AND c.newvalue IN (%s) 
                WHERE IN (%s) AND m.name IN (%s)""" % \
                    ( 
                        status_params, 
                        status_params, 
                        ("%s,"*len(mil_names))[:-1]
                    )
        else:
            base_sql = "SELECT MAX(c.time), t.id, t.type, "+db.cast(db.concat('0','tc.value'),'int')+ \
                """FROM ticket t 
                    LEFT JOIN milestone m ON m.name=t.milestone 
                    LEFT JOIN ticket_custom tc ON t.id=tc.ticket AND tc.name=%%s
                    LEFT OUTER JOIN ticket_change c ON t.id=c.ticket AND c.field='status' 
                        AND c.newvalue IN (%s) 
                WHERE t.status IN (%s) AND m.name IN (%s)""" % \
                    (
                        status_params, 
                        status_params, 
                        ("%s,"*len(mil_names))[:-1]
                    )
            params =[self.count_burndown_on] + params
            group_by +=", tc.value"
        if tkt_type:
            if isinstance(tkt_type, basestring):
                base_sql +=" AND t.type=%s"
                params +=[tkt_type]
            else:
                base_sql +=" AND t.type IN (%s)" % ("%s,"*len(tkt_type))[:-1]
                params += list(tkt_type)
        
        cursor.execute(base_sql+group_by+" ORDER BY 1", params)
        data = [(to_datetime((dt<started_at) and started_at or dt), ttype, sum or 0) 
            for dt, tkt_id, ttype, sum in  cursor]
        return data
