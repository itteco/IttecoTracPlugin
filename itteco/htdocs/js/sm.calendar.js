var cDate = new Date();
var startDate= new Date(cDate.getFullYear(), cDate.getMonth(), -7);
var endDate= new Date(cDate.getFullYear(), cDate.getMonth(), 37);

function adjustDateRange(){
   var needsReferesh = false;
   var c = eventCalendar;
   var dt = c.chosenDate;
   var left = dt.duplicate();
   var right = dt.duplicate();
   if (c.dayViewSelected()) {
        left= new Date(c.year, c.month, dt.getDate(),0, 0);
        right= new Date(c.year, c.month, dt.getDate(),23, 59);
    } else if (c.weekViewSelected()) {
        left= c.chosenWeekStart;
        right= c.chosenWeekEnd;
    } else {
        left = new Date(c.year, c.month, -7);
        right = new Date(c.year, c.month, 37);
    }
    if(left<startDate){
        needsReferesh = true;
        startDate = left;
    }
    if(right>endDate){
        needsReferesh = true;
        endDate = right;
    }
    
    return needsReferesh;
}
var needEventsFetching= true;
var inactiveCalendars = {};
var calendars = {};

function getCurrentCalendar(){
    var cal_id;
    $.each(calendars, function(idx){
        if(this.active)
            if(this.type!='R'){
                cal_id = this.calendarId;
                return false;
            }
    });
    
    return cal_id;
}

function hasActiveCalendar(){
    return typeof(getCurrentCalendar())!='undefined';
}
isc.DataSource.create({
    ID: "eventDS",
    dataFormat:"json",
    dataURL: eventsUrl,
    transformResponseToJS: false,
    fields:[
        {name:"eventId", primaryKey: true},
        {name:"ticket"},
        {name:"name"},
        {name:"description"},
        {name:"startDate", type: "datetime"},
        {name:"endDate", type: "datetime"},
        {name:"calendar"},
        {name:'timetrack'}, 
        {name:'auto'},
        {name:'time'}
    ],
    transformRequest : function (dsRequest) {
        var cDate = new Date();
        if(typeof(eventCalendar)=='object'){
            cDate = eventCalendar.chosenDate;
        }
        var params = {};
        if (dsRequest.operationType == "fetch") {
            params = {
                action :'read',
                dtstart : startDate.getTime(),
                dtend : endDate.getTime()
            };
        }
        if (dsRequest.operationType == "add" || dsRequest.operationType == "update") {
            var newRecord = dsRequest.originalData;
            var cCalendar = newRecord.calendar || getCurrentCalendar();
            params = {
                action: 'save',
                eventId: newRecord.eventId || '',
                name: newRecord.name,
                description: newRecord.description,
                startDate: newRecord.startDate.getTime(),
                endDate: newRecord.endDate.getTime(),
                calendar: cCalendar,
                ticket: newRecord.ticket || '',
                timetrac: newRecord.timetrack || ''
            };
            return isc.addProperties({}, dsRequest.data, params);
        }else if (dsRequest.operationType == "remove") {
            var newRecord = dsRequest.data;
            params = {
                action: 'delete',
                eventId: newRecord.eventId,
            };        
        }
        
        return isc.addProperties({}, dsRequest.data, params);
    },
    transformResponse : function (dsResponse){
        function decorateEvent(e){
            e.startDate = new Date(parseInt(e.startDate+'000'));
            e.endDate = new Date(parseInt(e.endDate+'000'));
            e.ticket = (e.ticket == 0) ? null : e.ticket;
            if(e.calendar){
                var calObj = calendars[e.calendar];
                e.isReference= typeof(calObj)=='object' && calObj.type =='R';
                if(calObj){
                    e.eventWindowStyle="calendarTheme"+calObj.theme;
                }
            }
        }
        
        var data = dsResponse.data;
        for(var i=0; i<data.length; i++){
            decorateEvent(data[i]);
        }
    }
});
isc.DataSource.create({
    ID: "calendarDS",
    dataFormat:"json",
    dataURL:calendarUrl,
    transformResponseToJS: false,
    fields:[
        {name:"calendarId", primaryKey: true},
        {name:"name"},
        {name:"type"},
        {name:"theme"}
    ],
    transformRequest : function (dsRequest) {
        var params = {};
        if (dsRequest.operationType == "fetch") {
            params = {
                action :'read',
            };
        }
        if (dsRequest.operationType == "add" || dsRequest.operationType == "update") {
            var newRecord = dsRequest.originalData;
            params = {
                action: 'save',
                calendarId: newRecord.calendarId || '',
                name: newRecord.name,
                type: newRecord.type,
                theme: newRecord.theme
            };
        }else if (dsRequest.operationType == "remove") {
            var newRecord = dsRequest.data;
            params = {
                action: 'delete',
                calendarId: newRecord.calendarId,
            };        
        }
        
        return isc.addProperties({}, dsRequest.data, params);
    },
    transformResponse : function (dsResponse){
        var data = dsResponse.data;
        $.each(data, function(idx){
            this.active = true;
            calendars[this.calendarId] = this;
            if(this.type!='R'){
                eventCalendar.canCreateEvents = true;
            }
        });
        if(needEventsFetching){
            needEventsFetching = false;
            eventCalendar.fetchData();
        }
    }
});
isc.DataSource.create({
    ID: "publicCalendarDS",
    dataFormat:"json",
    dataURL:calendarUrl,
    transformResponseToJS: false,
    fields:[
        {name:"calendarId", primaryKey: true},
        {name:"name"}
    ],
    transformRequest : function (dsRequest) {
        var params = {
            action :'read',
            shared : 'X'
        };
        return isc.addProperties({}, dsRequest.data, params);
    }
});

isc.DataSource.create({
    ID: "myTicketsDS",
    dataFormat:"json",
    dataURL:ticketsUrl,
    transformResponseToJS: false,
    fields:[
        {name:"ticketId", primaryKey: true},
        {name:"summary"}
    ],
    transformResponse : function (dsResponse){
        var data = dsResponse.data;
        $.each(data, function(idx){
            this.itemTitle= this.ticketId + ' ' +this.summary;
        });
    }
});
var timeTrackFields = [
    {type : 'header', defaultValue:"Time Tracking Options"},
    {name : 'ticket', type: 'comboBox', title: 'Ticket', optionDataSource: "myTicketsDS", valueField: "ticketId", displayField: "itemTitle", pickListWidth: 200, colSpan:4},
    {name : 'timetrack', type: 'checkbox', title: 'Timetrack', endRow: false}, 
    {name : 'auto', type: 'checkbox', title: 'Auto', startRow: false},
    {name : 'time', type: 'time', title: 'Time', colSpan: 3}
];
isc.HLayout.create({
    position:"relative",
    width:"95%",
    height:isc.Page.getHeight()-170,
    members: [
        isc.VLayout.create({
            width:"30%",
            height: "100%",
            members: [
                isc.IButton.create({
                    title: "Add Calendar",
                    click : function () {
                        calendarEditForm.editNewRecord();
                        modalWindow.show();
                    }
                }),
                isc.ListGrid.create({
                    ID: "calendarsList",
                    showResizeBar: true,
                    alternateRecordStyles:true, 
                    cellHeight: 20,
                    headerHeight: 40,
                    dataSource: calendarDS,
                    fields : [
                        {
                            name: "theme", 
                            width: 20
                        }, 
                        { name: "name"}, 
                        { name: "type", width: 20}
                    ],
                    headerSpans: [
                        {
                            fields: ["theme", "name", "type"], 
                            title: "Calendars"
                        }
                    ],
                    autoFetchData: true,
                    getBaseStyle: function (record, rowNum, colNum) {
                        if (colNum==0 && record){
                            if(record.active)
                                return "calendarTheme"+record.theme;
                        }
                        return this.Super('getBaseStyle', arguments);
                    },
                    cellDoubleClick: function(record, rowNum, colNum){
                        calendarEditForm.editRecord(record);
                        modalWindow.show();
                    },
                    cellClick: function(record, rowNum, colNum){
                        if(colNum==0){
                            record.active= !record.active;
                            calendars[record.calendarId].active = record.active;
                            var criter = {
                                _constructor:"AdvancedCriteria",
                                operator:"and",
                                criteria: []
                            };                        
                            $.each(calendars, function(idx){
                                if(!this.active){
                                    criter.criteria.push(
                                        { 
                                            fieldName: "calendar", 
                                            operator: "notEqual", 
                                            value: this.calendarId
                                        }
                                    );
                                }
                            });
                            eventCalendar.setCriteria(criter);
                            eventCalendar.canCreateEvents = hasActiveCalendar();
                            calendarsList.refreshRow(rowNum);
                        }
                    }
                }),
                isc.ListGrid.create({
                        ID: "ticketsList",
                        dataSource: myTicketsDS,
                        showResizeBar: true,
                        alternateRecordStyles:true, 
                        cellHeight: 20,
                        headerHeight: 40,
                        fields : [
                            {
                                name: "ticketId",
                                width: 35,
                                title: "#"
                            }, 
                            {
                                name: "summary"
                            }
                        ],
                        autoFetchData: true,
                        canDragRecordsOut: true,
                        canReorderRecords: true,
                        dragDataAction: "copy",
                        headerSpans: [
                            {
                                fields: ["ticketId", "summary"], 
                                title: "Tickets"
                            }
                        ]

                    })
            ]
        }),
        isc.Calendar.create({
            ID: "eventCalendar",
            dataSource: eventDS, 
            fetchMode : "month",
            firstDayOfWeek:1,
            canDeleteEvents:null,
            disableWeekends: false,
            eventDialogFields : [{name: 'name'}].concat(timeTrackFields).concat([{name : 'save', title: 'Save Event', type: "SubmitItem", endRow: false}]),
            eventEditorFields: [{name : 'description'}].concat(timeTrackFields),
            dateChanged: function(){
                if(adjustDateRange()){
                    this.filterData();
                }
            },
            filterData: function (criteria, callback, requestProperties){
                return this.Super('filterData', arguments);
            },
            eventRemoveClick: function(event, viewName){
                var calObj = calendars[event.calendar];
                return (calObj && calObj.type!='R');
            },
            canAcceptDrop: true,
            drop: function(){
                var data = isc.Event.getDragTarget().transferDragData();
                var dto = (isc.isAn.Array(data) ? data[0] : data);
                var sDate= this.getActiveTime();
                var eDate= this.getActiveTime();
                eDate.setMinutes(eDate.getMinutes()+30);
                
                var event = dto && 
                    {name: dto.summary, ticket: dto.ticketId, startDate: sDate, endDate: eDate,
                     timetrack: true, auto: true} 
                    || {};
                this.eventDialog.event = null;
                var form = this.eventDialog.items[0];
                form.createFields(true);
                this.eventDialog.setEvent(event);
                this.eventDialog.event = null;
                if (this.eventEditorLayout) this.eventEditorLayout.event = null;
                
                this.eventDialog.show();

                var currView = this.getSelectedView();
                var coords = currView.getCellPageRect(currView.getEventRow(), currView.getEventColumn());
                this.eventDialog.placeNear(coords[0], coords[1]);
                return true;
            }
        })
    ]
});

isc.Window.create({
    ID: "modalWindow",
    title: "Calendar Properties",
    autoSize:true,
    autoCenter: true,
    isModal: true,
    showModalMask: true,
    autoDraw: false,
    width: 420,
    items: [
        isc.DynamicForm.create({
            ID: "calendarEditForm",
            titleOrientation: "top",
            autoDraw: false,
            height: 48,
            colWidths: [140, 140, 140],
            numCols: 3,
            padding:4,
            dataSource: calendarDS,
            fields: [
                {name: "type", type: "radioGroup", valueMap: {P:"Keep it Private", S:"Share with Everyone", R:"Add Shared Calendar"},
                    vertical: false, title : "Sharing", colSpan: 3, required: true, defaultValue: 'P',
                    change: "if(value!='R'){form.getField('ref').hide();}else{form.getField('ref').show();}"
                },
                {name: "ref", title:"Referenced", type:"select",
                  optionDataSource:"publicCalendarDS",
                  valueField:"calendarId", displayField:"name",
                  showTitle: false, align: 'right',
                  change: "form.getField('name').setValue(this.mapValueToDisplay(value))",
                  colSpan: 3,
                },
                {name: "name", title: "Display Name", colSpan: 3, required: true, width: "*"},                
                {name: "theme", type:"select",  colSpan: 3, required: true, valueMap: 
                    { 
                        1:'<div class="calendarTheme1">Theme 1</div>',
                        2:'<div class="calendarTheme2">Theme 2</div>',
                        3:'<div class="calendarTheme3">Theme 3</div>',
                        4:'<div class="calendarTheme4">Theme 4</div>',
                        5:'<div class="calendarTheme5">Theme 5</div>',
                        6:'<div class="calendarTheme6">Theme 6</div>',
                        7:'<div class="calendarTheme7">Theme 7</div>'
                    }
                },
                {type: "button", title: "Save", endRow: false,
                    click: "calendarEditForm.saveData(function(){calendarsList.filterData();modalWindow.hide();});" 
                },
                {type: "button", title: "Delete", showIf: "typeof(values.calendarId)!='undefined'",  startRow: false,
                    click: "calendarDS.removeData(form.getValues(),function(){calendarsList.filterData()});modalWindow.hide();" 
                }
            ]
        })
    ]
});

var observer = isc.Class.create({
    adjustRelationsMonitor : function(dialog){
        if(hasActiveCalendar()){
          var f = dialog.items[0];
          var observer = this;
          f.itemChanged = function(item, newValue){observer.adjustFieldsState(f, item, newValue); };
          this.adjustFieldsState(f);
          this.setDefaults(f);
        }else{
            dialog.hide();
            isc.warn('In order to create events you need to create and activate your own calendar.');
        }
    },
    
    adjustFieldsState: function(form, item, newValue){
      var f = form;
      var e = form.getParentElements()[1].event;
      var detailsField = f.getField('details');
      if(e && e.isReference){
        f.getField('ticket').setDisabled(true);
        if(detailsField) detailsField.hide();
      }else{
        f.getField('ticket').setDisabled(false);
        if(detailsField) detailsField.show();
      }
      var timeTrackEnabled = f.getField('timetrack').getValue();
      f.getField('auto').setDisabled(!timeTrackEnabled);

      var autoTimeSetup= f.getField('auto').getValue();
      f.getField('time').setDisabled(autoTimeSetup || !timeTrackEnabled);

      if(autoTimeSetup){
        var time = this.calculateTime(f);
        f.getField('time').setValue(time);
      }
    },
    setDefaults : function(form){
      var e = form.getParentElements()[1].event;
      if(!e){
        form.getField('auto').setValue(true);
        var time = this.calculateTime(form);
        form.getField('time').setValue(time);    
      }
    },
    calculateTime : function(form){
        if (form.getItem("startHours") == undefined){
            return this.calculateTimeByEvent(form);
        }else{
            return this.calculateTimeByFields(form);
        }
    },
    calculateTimeByFields : function(form){
        var sHrs = form.getItem("startHours").getValue(),
            eHrs = form.getItem("endHours").getValue(),
            sMins = form.getItem("startMinutes").getValue(), 
            eMins = form.getItem("endMinutes").getValue()
        ; 
        var sAMPM, eAMPM;
           
        if (!eventCalendar.twentyFourHourTime) {
            sAMPM = form.getItem("startAMPM").getValue();
            eAMPM = form.getItem("endAMPM").getValue();
            sHrs = this._to24HourNotation(sHrs, sAMPM);
            eHrs = this._to24HourNotation(eHrs, eAMPM);
            if (eHrs == 0) eHrs = 24;
        }
        if ((sHrs < eHrs || (sHrs == eHrs && sMins < eMins))) {
            hh = eHrs - sHrs;
            mm = eMins - sMins;
            if(mm<0){
                mm = mm +60;
                hh = hh -1;
            }
            return hh+':' +mm;
        }
    },
    calculateTimeByEvent : function(form){
        var dialog = form.getParentElements()[1];
        var event = dialog.event;
        
        var diff = dialog.currentEnd - dialog.currentStart;
        if(event){
            diff = event.endDate.getTime() - event.startDate.getTime();           
        }
        return Math.floor(diff / 3600000) + ':'+ (diff /60000 % 60);
    },
        
    _to24HourNotation: function (hour, ampmString) {
        // make sure we're dealing with an int
        hour = parseInt(hour);
        if (ampmString.toLowerCase() == "am" && hour == 12) { 
            return 0;
        } else if (ampmString.toLowerCase() == "pm" && hour < 12) {
            return hour + 12;    
        } else {
            return hour;    
        }
    }

});
observer.observe(eventCalendar.eventDialog, 'show', 'observer.adjustRelationsMonitor(this)');
observer.observe(eventCalendar.eventEditorLayout, 'show', 'observer.adjustRelationsMonitor(this)');