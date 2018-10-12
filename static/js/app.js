$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port);

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(msg.temp + "°");
    });

    socket.on('connected', function(msg){
        console.log("Connected")
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }
    });

    $('#enabled').change(function() {
        if(this.checked) {
            socket.emit('enable_system', {data: 'disabled'});
        } else {
            socket.emit('disable_system', {data: 'enabled'});
        }      
    });

    $('#desired-temp').change( function() {
        console.log(this.value);
        socket.emit('set_temperature', this.value);
    });​
});
