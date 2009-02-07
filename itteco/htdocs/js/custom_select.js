toggleDD=function(obj){    
    var o=$(obj); 
    o.next().css('width', o.parent().attr('clientWidth')).toggle();
    console.log('togglingDD'+o);
    if(o.next(":visible").length>0){
        console.log('binding document togglingDD');
        o.next().add(o).bind('mouseout', null, 
            function(e){
                $(document).one('click',null, function(e){toggleDD(obj)});
            }).bind('mouseover', null,
            function(e){
                $(document).unbind('click');
            })
    }else{
        o.next().add(o).unbind('mouseout').unbind('mouseover');
        $(document).unbind('click');
    }
}    
mouse_in_out=function(event){$(this).toggleClass('focused_drop_down_item');}
clickDDI=function(event){
    var o = $(this);
    o.siblings().removeClass('selected_drop_down_item');
    o.addClass('selected_drop_down_item');
    var par = o.parent();
    par.next().attr('value',o.attr('empty') ? '' : o.children('em:first').text()); 
    par.prev().text(o.text());
    toggleDD(par.prev());
}

$(document).ready(function(){
    $("div.custom_drop_down_box").children().bind('mouseover',null,mouse_in_out).bind('mouseout',null,mouse_in_out).bind('click',null,clickDDI);
    $("div.custom_drop_down").bind('reset',null, function(e){var o =$(this);var val=o.siblings(":hidden:last").val();o.siblings(":hidden").val(val);o.text(val)});

})